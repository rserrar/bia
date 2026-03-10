<?php

declare(strict_types=1);

require_once __DIR__ . '/../src/StateStore.php';
require_once __DIR__ . '/../src/ApiService.php';

use V2ServerApi\ApiService;
use V2ServerApi\StateStore;

function envValue(string $key, string $default = ''): string
{
    $value = getenv($key);
    if ($value === false || $value === '') {
        return $default;
    }
    return $value;
}

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

$stateFile = envValue('V2_STATE_FILE', realpath(__DIR__ . '/..') . '/../state/state.json');
$store = new StateStore($stateFile);
$service = new ApiService($store);

requireTokenIfConfigured();

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
$path = is_string($path) ? trim($path, '/') : '';
$parts = $path === '' ? [] : explode('/', $path);

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

    if ($method === 'GET' && count($parts) === 2 && $parts[0] === 'runs') {
        respond(200, $service->getRun($parts[1]));
    }

    if ($method === 'GET' && count($parts) === 3 && $parts[0] === 'runs' && $parts[2] === 'summary') {
        respond(200, $service->getSummary($parts[1]));
    }

    respond(404, ['error' => 'not_found']);
} catch (RuntimeException $error) {
    $message = $error->getMessage();
    if ($message === 'run not found') {
        respond(404, ['error' => $message]);
    }
    respond(400, ['error' => $message]);
} catch (Throwable $error) {
    respond(500, ['error' => 'internal_error']);
}
