<?php

declare(strict_types=1);

require_once __DIR__ . '/../src/StateStore.php';
if (is_file(__DIR__ . '/../src/SqliteStateStore.php')) {
    require_once __DIR__ . '/../src/SqliteStateStore.php';
}
require_once __DIR__ . '/../src/ApiService.php';

use V2ServerApi\ApiService;
use V2ServerApi\SqliteStateStore;
use V2ServerApi\StateStore;

function loadDotEnvFiles(array $paths): void
{
    foreach ($paths as $path) {
        if (!is_string($path) || $path === '' || !is_file($path)) {
            continue;
        }
        $lines = file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
        if ($lines === false) {
            continue;
        }
        foreach ($lines as $line) {
            $trimmed = trim((string) $line);
            if ($trimmed === '' || str_starts_with($trimmed, '#')) {
                continue;
            }
            if (str_starts_with($trimmed, 'export ')) {
                $trimmed = trim(substr($trimmed, 7));
            }
            $separatorPos = strpos($trimmed, '=');
            if ($separatorPos === false || $separatorPos < 1) {
                continue;
            }
            $key = trim(substr($trimmed, 0, $separatorPos));
            $value = trim(substr($trimmed, $separatorPos + 1));
            if ($key === '' || getenv($key) !== false) {
                continue;
            }
            $firstChar = $value !== '' ? $value[0] : '';
            $lastChar = $value !== '' ? $value[strlen($value) - 1] : '';
            if (($firstChar === '"' && $lastChar === '"') || ($firstChar === "'" && $lastChar === "'")) {
                $value = substr($value, 1, -1);
            }
            putenv("{$key}={$value}");
            $_ENV[$key] = $value;
            $_SERVER[$key] = $value;
        }
    }
}

function envValue(string $key, string $default = ''): string
{
    $value = getenv($key);
    if ($value === false || $value === '') {
        return $default;
    }
    return $value;
}

loadDotEnvFiles([
    getenv('V2_DOTENV_PATH') ?: '',
    __DIR__ . '/../.env',
    __DIR__ . '/../../.env',
]);

function jsonInput(): array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || trim($raw) === '') {
        return [];
    }
    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) {
        throw new RuntimeException('invalid json body');
    }
    return $decoded;
}

function respond(int $status, array $payload): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

function requireTokenIfConfigured(): void
{
    $expectedToken = envValue('V2_API_TOKEN', '');
    if ($expectedToken === '') {
        return;
    }
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    if (!str_starts_with($header, 'Bearer ')) {
        respond(401, ['error' => 'unauthorized']);
    }
    $token = substr($header, 7);
    if (!hash_equals($expectedToken, $token)) {
        respond(401, ['error' => 'unauthorized']);
    }
}

function requestPathParts(): array
{
    $requestPath = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
    $path = is_string($requestPath) ? $requestPath : '/';
    $scriptName = (string) ($_SERVER['SCRIPT_NAME'] ?? '');
    $scriptDir = rtrim(str_replace('\\', '/', dirname($scriptName)), '/');
    $prefixes = [
        $scriptName,
        $scriptDir,
        '/index.php',
    ];
    foreach ($prefixes as $prefix) {
        if (!is_string($prefix) || $prefix === '' || $prefix === '/' || $prefix === '.') {
            continue;
        }
        if ($path === $prefix) {
            $path = '/';
            break;
        }
        if (str_starts_with($path, $prefix . '/')) {
            $path = substr($path, strlen($prefix));
            if ($path === false || $path === '') {
                $path = '/';
            }
            break;
        }
    }
    $trimmed = trim($path, '/');
    return $trimmed === '' ? [] : explode('/', $trimmed);
}

try {
    $storageBackend = strtolower(envValue('V2_STORAGE_BACKEND', 'json'));
    if ($storageBackend === 'sqlite') {
        $sqlitePath = envValue('V2_SQLITE_PATH', realpath(__DIR__ . '/..') . '/../state/state.sqlite');
        try {
            $store = new SqliteStateStore($sqlitePath);
        } catch (Throwable $error) {
            $fallbackToJson = in_array(strtolower(envValue('V2_STORAGE_FALLBACK_JSON', 'true')), ['1', 'true', 'yes'], true);
            if (!$fallbackToJson) {
                respond(500, ['error' => 'storage_init_error', 'backend' => 'sqlite', 'detail' => $error->getMessage()]);
            }
            $stateFile = envValue('V2_STATE_FILE', realpath(__DIR__ . '/..') . '/../state/state.json');
            $store = new StateStore($stateFile);
        }
    } else {
        $stateFile = envValue('V2_STATE_FILE', realpath(__DIR__ . '/..') . '/../state/state.json');
        $store = new StateStore($stateFile);
    }
} catch (Throwable $error) {
    respond(500, ['error' => 'storage_init_error', 'detail' => $error->getMessage()]);
}
$service = new ApiService($store);

requireTokenIfConfigured();

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$parts = requestPathParts();

try {
    if ($method === 'POST' && $parts === ['runs']) {
        $body = jsonInput();
        $created = $service->createRun($body['code_version'] ?? 'dev', $body['metadata'] ?? []);
        respond(201, $created);
    }

    if ($method === 'POST' && count($parts) === 3 && $parts[0] === 'runs' && $parts[2] === 'heartbeat') {
        respond(200, $service->heartbeat($parts[1]));
    }

    if ($method === 'POST' && count($parts) === 3 && $parts[0] === 'runs' && $parts[2] === 'status') {
        $body = jsonInput();
        $generation = array_key_exists('generation', $body) ? (int) $body['generation'] : null;
        respond(200, $service->updateStatus($parts[1], (string) ($body['status'] ?? ''), $generation));
    }

    if ($method === 'POST' && count($parts) === 3 && $parts[0] === 'runs' && $parts[2] === 'events') {
        $body = jsonInput();
        respond(
            201,
            $service->addEvent(
                $parts[1],
                (string) ($body['event_type'] ?? ''),
                (string) ($body['label'] ?? ''),
                is_array($body['details'] ?? null) ? $body['details'] : []
            )
        );
    }

    if ($method === 'POST' && count($parts) === 3 && $parts[0] === 'runs' && $parts[2] === 'metrics') {
        $body = jsonInput();
        respond(
            201,
            $service->addMetric(
                $parts[1],
                (string) ($body['model_id'] ?? ''),
                (int) ($body['generation'] ?? 0),
                is_array($body['metrics'] ?? null) ? $body['metrics'] : []
            )
        );
    }

    if ($method === 'POST' && count($parts) === 3 && $parts[0] === 'runs' && $parts[2] === 'artifacts') {
        $body = jsonInput();
        respond(
            201,
            $service->addArtifact(
                $parts[1],
                (string) ($body['artifact_type'] ?? ''),
                (string) ($body['uri'] ?? ''),
                (string) ($body['storage'] ?? 'drive'),
                isset($body['checksum']) ? (string) $body['checksum'] : null,
                is_array($body['metadata'] ?? null) ? $body['metadata'] : []
            )
        );
    }

    if ($method === 'POST' && $parts === ['maintenance', 'watchdog']) {
        $body = jsonInput();
        $staleAfterSeconds = (int) ($body['stale_after_seconds'] ?? 120);
        respond(200, $service->markStaleRunsRetrying($staleAfterSeconds));
    }

    if ($method === 'POST' && $parts === ['maintenance', 'process-model-proposals-phase0']) {
        $body = jsonInput();
        $limit = (int) ($body['limit'] ?? 20);
        respond(200, $service->processQueuedModelProposalsPhase0($limit));
    }

    if ($method === 'POST' && $parts === ['model-proposals']) {
        $body = jsonInput();
        respond(
            201,
            $service->createModelProposal(
                (string) ($body['source_run_id'] ?? ''),
                (string) ($body['base_model_id'] ?? ''),
                is_array($body['proposal'] ?? null) ? $body['proposal'] : [],
                is_array($body['llm_metadata'] ?? null) ? $body['llm_metadata'] : []
            )
        );
    }

    if ($method === 'GET' && $parts === ['model-proposals']) {
        $limitParam = $_GET['limit'] ?? '100';
        $limit = is_numeric($limitParam) ? (int) $limitParam : 100;
        if ($limit <= 0) {
            $limit = 100;
        }
        respond(200, ['model_proposals' => $service->listModelProposals($limit)]);
    }

    if ($method === 'GET' && $parts === ['proposals']) {
        $limitParam = $_GET['limit'] ?? '100';
        $limit = is_numeric($limitParam) ? (int) $limitParam : 100;
        if ($limit <= 0) {
            $limit = 100;
        }
        respond(200, ['proposals' => $service->listUiProposals($limit)]);
    }

    if ($method === 'GET' && count($parts) === 2 && $parts[0] === 'model-proposals') {
        respond(200, $service->getModelProposal($parts[1]));
    }

    if ($method === 'POST' && count($parts) === 3 && $parts[0] === 'model-proposals' && $parts[2] === 'status') {
        $body = jsonInput();
        $metadataUpdates = is_array($body['metadata_updates'] ?? null) ? $body['metadata_updates'] : [];
        respond(200, $service->updateProposalStatus($parts[1], (string) ($body['status'] ?? ''), $metadataUpdates));
    }

    if ($method === 'POST' && count($parts) === 3 && $parts[0] === 'model-proposals' && $parts[2] === 'enqueue-phase0') {
        respond(200, $service->enqueueModelProposalPhase0($parts[1]));
    }

    if ($method === 'POST' && $parts === ['model-proposals', 'lock-for-training']) {
        $body = jsonInput();
        $trainerId = (string) ($body['trainer_id'] ?? 'unknown_trainer');
        $locked = $service->lockAcceptedProposalForTraining($trainerId);
        if ($locked === null) {
            respond(200, []);
        }
        respond(200, $locked);
    }

    if ($method === 'GET' && $parts === ['runs']) {
        $limitParam = $_GET['limit'] ?? '100';
        $limit = is_numeric($limitParam) ? (int) $limitParam : 100;
        if ($limit <= 0) {
            $limit = 100;
        }
        respond(200, ['runs' => $service->listRuns($limit)]);
    }

    if ($method === 'GET' && $parts === ['events']) {
        $limitParam = $_GET['limit'] ?? '50';
        $limit = is_numeric($limitParam) ? (int) $limitParam : 50;
        if ($limit <= 0) {
            $limit = 50;
        }
        respond(200, ['events' => $service->listEvents($limit)]);
    }

    if ($method === 'GET' && $parts === ['metrics']) {
        $limitParam = $_GET['limit'] ?? '50';
        $limit = is_numeric($limitParam) ? (int) $limitParam : 50;
        if ($limit <= 0) {
            $limit = 50;
        }
        respond(200, ['metrics' => $service->listMetrics($limit)]);
    }

    if ($method === 'GET' && count($parts) === 2 && $parts[0] === 'runs') {
        respond(200, $service->getRun($parts[1]));
    }

    if ($method === 'GET' && count($parts) === 3 && $parts[0] === 'runs' && $parts[2] === 'summary') {
        respond(200, $service->getSummary($parts[1]));
    }

    if ($method === 'GET' && count($parts) === 3 && $parts[0] === 'runs' && $parts[2] === 'references') {
        $limitParam = $_GET['limit'] ?? '10';
        $limit = is_numeric($limitParam) ? (int) $limitParam : 10;
        if ($limit <= 0) {
            $limit = 10;
        }
        respond(200, $service->getRunReferences($parts[1], $limit));
    }

    if ($method === 'GET' && count($parts) === 3 && $parts[0] === 'champion' && $parts[1] === 'run') {
        $topNParam = $_GET['top_n'] ?? '5';
        $topN = is_numeric($topNParam) ? (int) $topNParam : 5;
        if ($topN <= 0) {
            $topN = 5;
        }
        respond(200, $service->getChampionRun($parts[2], $topN));
    }

    if ($method === 'GET' && $parts === ['champion', 'global']) {
        $topNParam = $_GET['top_n'] ?? '5';
        $topN = is_numeric($topNParam) ? (int) $topNParam : 5;
        if ($topN <= 0) {
            $topN = 5;
        }
        respond(200, $service->getChampionGlobal($topN));
    }

    if ($method === 'GET' && $parts === ['models', 'shortlist']) {
        $limitParam = $_GET['limit'] ?? '10';
        $limit = is_numeric($limitParam) ? (int) $limitParam : 10;
        if ($limit <= 0) {
            $limit = 10;
        }
        respond(200, $service->getModelsShortlist($limit));
    }

    if ($method === 'GET' && count($parts) === 3 && $parts[0] === 'runs' && $parts[2] === 'events') {
        $limitParam = $_GET['limit'] ?? '200';
        $limit = is_numeric($limitParam) ? (int) $limitParam : 200;
        if ($limit <= 0) {
            $limit = 200;
        }
        respond(200, ['events' => $service->listRunEvents($parts[1], $limit)]);
    }

    respond(404, ['error' => 'not_found']);
} catch (RuntimeException $error) {
    $message = $error->getMessage();
    if ($message === 'run not found' || $message === 'proposal not found') {
        respond(404, ['error' => $message]);
    }
    respond(400, ['error' => $message]);
} catch (Throwable $error) {
    respond(500, ['error' => 'internal_error']);
}
