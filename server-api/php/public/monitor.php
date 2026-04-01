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

function redirectToMonitorHome(): void
{
    header('Location: ./monitor.php');
    exit;
}

function formatDurationShort($seconds): string
{
    if (!is_numeric($seconds)) {
        return '-';
    }
    $total = max(0, (int) round((float) $seconds));
    $hours = intdiv($total, 3600);
    $minutes = intdiv($total % 3600, 60);
    $secs = $total % 60;
    if ($hours > 0) {
        return sprintf('%dh %02dm', $hours, $minutes);
    }
    if ($minutes > 0) {
        return sprintf('%dm %02ds', $minutes, $secs);
    }
    return sprintf('%ds', $secs);
}

function inferExecutionRunId(array $request, string $latestRunId): string
{
    $currentRunId = (string) ($request['current_run_id'] ?? '');
    if ($currentRunId !== '') {
        return $currentRunId;
    }
    $runIds = is_array($request['run_ids'] ?? null) ? $request['run_ids'] : [];
    if (count($runIds) > 0) {
        return (string) ($runIds[0] ?? '');
    }
    $status = (string) ($request['status'] ?? '');
    if (!in_array($status, ['claimed', 'running'], true)) {
        return '';
    }
    return $latestRunId;
}

function inferExecutionProgress(array $request, string $inferredRunId, array $runsById, array $proposals): array
{
    $progress = is_array($request['progress'] ?? null) ? $request['progress'] : [];
    if ($inferredRunId === '') {
        return $progress;
    }
    $run = is_array($runsById[$inferredRunId] ?? null) ? $runsById[$inferredRunId] : [];
    $runGeneration = (int) ($run['generation'] ?? 0);
    $matching = array_values(array_filter(
        $proposals,
        static fn(array $proposal): bool => (string) ($proposal['source_run_id'] ?? '') === $inferredRunId
    ));
    $modelsGenerated = count($matching);
    $modelsTrained = count(array_filter($matching, static fn(array $proposal): bool => (string) ($proposal['status'] ?? '') === 'trained'));
    if ($modelsGenerated === 0 && $runGeneration === 0) {
        return $progress;
    }
    $generationsTotal = (int) ($progress['generations_total'] ?? ($request['config']['generations'] ?? 1));
    $progress['generations_total'] = max(1, $generationsTotal);
    $progress['generations_completed'] = max((int) ($progress['generations_completed'] ?? 0), $runGeneration);
    $progress['models_generated'] = max((int) ($progress['models_generated'] ?? 0), $modelsGenerated);
    $progress['models_trained'] = max((int) ($progress['models_trained'] ?? 0), $modelsTrained);
    if ($progress['generations_total'] > 0) {
        $progress['progress_percent'] = min(100, round((($progress['generations_completed'] / $progress['generations_total']) * 100), 1));
    }
    return $progress;
}

function estimateExecutionDurationMinutes(array $config): int
{
    $profile = strtolower((string) ($config['profile'] ?? 'small_test'));
    $generations = max(1, (int) ($config['generations'] ?? 1));
    $modelsPerGeneration = max(1, (int) ($config['models_per_generation'] ?? 1));
    $perModel = match ($profile) {
        'real_large' => 18,
        'default' => 8,
        default => 4,
    };
    return max(2, $generations * $modelsPerGeneration * $perModel);
}

function executionProfileExplanation(string $profile): string
{
    return match (strtolower($profile)) {
        'real_large' => 'Dataset gran i execució costosa; orientat a qualitat real.',
        'default' => 'Configuració equilibrada entre temps i qualitat.',
        default => 'Execució ràpida per validar pipeline i control operatiu.',
    };
}

function championOutcomeExplanation(string $eventType): string
{
    return match ($eventType) {
        'champion_selected' => 'Nou champion seleccionat',
        'champion_kept' => 'S’ha mantingut el champion anterior',
        'champion_selection_skipped' => 'Selecció de champion omesa',
        default => $eventType,
    };
}

function executionReferenceSummary(array $resultSummary): string
{
    $referenceContext = is_array($resultSummary['reference_context'] ?? null) ? $resultSummary['reference_context'] : [];
    $primaryReference = is_array(($referenceContext['references'] ?? [])[0] ?? null) ? $referenceContext['references'][0] : [];
    $referenceId = (string) ($referenceContext['primary_reference_proposal_id'] ?? $primaryReference['proposal_id'] ?? '');
    if ($referenceId === '') {
        return 'sense referència visible';
    }
    $reason = (string) ($referenceContext['primary_reference_reason'] ?? $primaryReference['selection_reason'] ?? '');
    if ($reason === '') {
        return $referenceId;
    }
    return $referenceId . ' · ' . $reason;
}

function executionRepairSummary(array $resultSummary): string
{
    $proposalId = (string) ($resultSummary['proposal_id'] ?? '');
    if ($proposalId === '') {
        return '';
    }
    $repairFrom = (string) ($resultSummary['repaired_from_proposal_id'] ?? '');
    $repairMode = (string) ($resultSummary['repair_mode'] ?? '');
    if ($repairFrom === '') {
        return '';
    }
    $label = 'reparat de ' . $repairFrom;
    if ($repairMode !== '') {
        $label .= ' · ' . $repairMode;
    }
    return $label;
}

function requestTypeExplanation(string $requestType): string
{
    return match ($requestType) {
        'smoke_run' => 'Prova ràpida end-to-end.',
        'micro_training' => 'Entrenament curt real.',
        'integration_matrix' => 'Múltiples runs per validar consistència.',
        'resume_training' => 'Reprèn entrenaments interromputs.',
        'cleanup' => 'Neteja estat inconsistent.',
        default => 'Tipus d’execució personalitzat.',
    };
}

function artifactAvailabilityLabel(array $resultSummary): string
{
    $artifactType = (string) ($resultSummary['latest_artifact_type'] ?? '');
    return $artifactType === '' ? 'missing' : 'available';
}

function llmResponseTextFromMetadata(array $llmMetadata): string
{
    $responseText = (string) ($llmMetadata['response_text'] ?? '');
    if ($responseText !== '') {
        return $responseText;
    }
    $rawResponse = is_array($llmMetadata['raw_response'] ?? null) ? $llmMetadata['raw_response'] : [];
    if (is_string($rawResponse['sdk_text'] ?? null)) {
        return (string) $rawResponse['sdk_text'];
    }
    $choices = is_array($rawResponse['choices'] ?? null) ? $rawResponse['choices'] : [];
    $firstChoice = is_array($choices[0] ?? null) ? $choices[0] : [];
    $message = is_array($firstChoice['message'] ?? null) ? $firstChoice['message'] : [];
    if (is_string($message['content'] ?? null)) {
        return (string) $message['content'];
    }
    if (is_string($firstChoice['text'] ?? null)) {
        return (string) $firstChoice['text'];
    }
    return '';
}

function requestAlertBadges(array $request): array
{
    $status = (string) ($request['status'] ?? '');
    $heartbeatAt = strtotime((string) ($request['heartbeat_at'] ?? '')) ?: 0;
    $updatedAt = strtotime((string) ($request['updated_at'] ?? '')) ?: 0;
    $now = time();
    $progress = is_array($request['progress'] ?? null) ? $request['progress'] : [];
    $generationsCompleted = (int) ($progress['generations_completed'] ?? 0);
    $modelsGenerated = (int) ($progress['models_generated'] ?? 0);
    $elapsedSeconds = (int) ($request['elapsed_seconds'] ?? 0);
    $badges = [];

    if ($status === 'failed') {
        $badges[] = ['label' => 'failed', 'class' => 'badge-danger'];
    }
    if ($status === 'cancelled') {
        $badges[] = ['label' => 'cancelled', 'class' => 'badge-muted'];
    }
    if (in_array($status, ['claimed', 'running'], true) && $heartbeatAt > 0 && ($now - $heartbeatAt) > 120) {
        $badges[] = ['label' => 'stale heartbeat', 'class' => 'badge-warning'];
        $badges[] = ['label' => 'reclaimable', 'class' => 'badge-warning'];
    }
    if ($status === 'running' && $elapsedSeconds >= 60 && $generationsCompleted === 0 && $modelsGenerated === 0) {
        $badges[] = ['label' => 'running sense progrés', 'class' => 'badge-warning'];
    }
    if ($status === 'claimed' && $updatedAt > 0 && ($now - $updatedAt) > 45) {
        $badges[] = ['label' => 'esperant worker', 'class' => 'badge-muted'];
    }

    return $badges;
}

function hiddenConfigInputs(string $requestType, array $config): string
{
    $inputs = '<input type="hidden" name="action" value="execution_request_create">';
    $inputs .= '<input type="hidden" name="request_type" value="' . htmlspecialchars($requestType, ENT_QUOTES, 'UTF-8') . '">';
    foreach ($config as $key => $value) {
        $serialized = is_bool($value) ? ($value ? '1' : '0') : (string) $value;
        $inputs .= '<input type="hidden" name="' . htmlspecialchars((string) $key, ENT_QUOTES, 'UTF-8') . '" value="' . htmlspecialchars($serialized, ENT_QUOTES, 'UTF-8') . '">';
    }
    return $inputs;
}

function monitorCredentials(): array
{
    return [
        'username' => 'admin',
        'password' => 'bia-v2-monitor',
    ];
}

function ensureMonitorSessionIfConfigured(): void
{
    if (session_status() !== PHP_SESSION_ACTIVE) {
        session_start();
    }
    $expectedToken = envValue('V2_API_TOKEN', '');
    if ($expectedToken === '') {
        $_SESSION['monitor_auth'] = true;
        return;
    }

    if (isset($_GET['logout'])) {
        $_SESSION = [];
        session_destroy();
        redirectToMonitorHome();
    }

    if (($_SESSION['monitor_auth'] ?? false) === true) {
        return;
    }

    $loginError = '';
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && (string) ($_POST['action'] ?? '') === 'login') {
        $username = is_string($_POST['username'] ?? null) ? trim((string) $_POST['username']) : '';
        $password = is_string($_POST['password'] ?? null) ? (string) $_POST['password'] : '';
        $credentials = monitorCredentials();
        if (
            hash_equals($credentials['username'], $username)
            && hash_equals($credentials['password'], $password)
        ) {
            $_SESSION['monitor_auth'] = true;
            session_regenerate_id(true);
            redirectToMonitorHome();
        }
        $loginError = 'Usuari o contrasenya incorrectes.';
    }

    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    $queryToken = is_string($_GET['token'] ?? null) ? (string) $_GET['token'] : '';
    $headerToken = '';
    if (str_starts_with($header, 'Bearer ')) {
        $headerToken = substr($header, 7);
    }
    $authorized = ($queryToken !== '' && hash_equals($expectedToken, $queryToken))
        || ($headerToken !== '' && hash_equals($expectedToken, $headerToken));
    if ($authorized === true) {
        $_SESSION['monitor_auth'] = true;
        session_regenerate_id(true);
        if ($queryToken !== '') {
            redirectToMonitorHome();
        }
        return;
    }
    http_response_code(401);
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><html lang="ca"><head><meta charset="utf-8"><title>V2 Monitor Login</title></head><body>';
    echo '<h1>V2 Monitor</h1>';
    echo '<p>Inicia sessió amb usuari i contrasenya.</p>';
    if ($loginError !== '') {
        echo '<p style="color:#b91c1c;">' . htmlspecialchars($loginError, ENT_QUOTES, 'UTF-8') . '</p>';
    }
    echo '<form method="post" action="./monitor.php">';
    echo '<input type="hidden" name="action" value="login">';
    echo '<input type="text" name="username" placeholder="Usuari" required>';
    echo '<input type="password" name="password" placeholder="Contrasenya" required>';
    echo '<button type="submit">Entrar</button>';
    echo '</form>';
    if ($expectedToken !== '') {
        echo '<hr><p>Alternativa: token (mode compatible)</p>';
        echo '<form method="get" action="./monitor.php">';
        echo '<input type="password" name="token" placeholder="Token">';
        echo '<button type="submit">Entrar amb token</button>';
        echo '</form>';
    }
    echo '</body></html>';
    exit;
}

function buildStore()
{
    $storageBackend = strtolower(envValue('V2_STORAGE_BACKEND', 'json'));
    if ($storageBackend === 'sqlite') {
        $sqlitePath = envValue('V2_SQLITE_PATH', realpath(__DIR__ . '/..') . '/../state/state.sqlite');
        try {
            return new SqliteStateStore($sqlitePath);
        } catch (Throwable $error) {
            $fallbackToJson = in_array(strtolower(envValue('V2_STORAGE_FALLBACK_JSON', 'true')), ['1', 'true', 'yes'], true);
            if (!$fallbackToJson) {
                throw $error;
            }
            $stateFile = envValue('V2_STATE_FILE', realpath(__DIR__ . '/..') . '/../state/state.json');
            return new StateStore($stateFile);
        }
    }
    $stateFile = envValue('V2_STATE_FILE', realpath(__DIR__ . '/..') . '/../state/state.json');
    return new StateStore($stateFile);
}

function monitorApiBaseUrl(): string
{
    $scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
    $host = (string) ($_SERVER['HTTP_HOST'] ?? 'localhost');
    $scriptDir = rtrim(str_replace('\\', '/', dirname((string) ($_SERVER['SCRIPT_NAME'] ?? '/monitor.php'))), '/');
    return $scheme . '://' . $host . ($scriptDir === '' ? '' : $scriptDir) . '/index.php';
}

function monitorApiRequest(string $path): array
{
    $baseUrl = monitorApiBaseUrl();
    $url = $baseUrl . $path;
    $headers = ["Accept: application/json"];
    $expectedToken = envValue('V2_API_TOKEN', '');
    if ($expectedToken !== '') {
        $headers[] = 'Authorization: Bearer ' . $expectedToken;
    }
    $context = stream_context_create([
        'http' => [
            'method' => 'GET',
            'header' => implode("\r\n", $headers),
            'ignore_errors' => true,
            'timeout' => 20,
        ],
    ]);
    $raw = @file_get_contents($url, false, $context);
    if ($raw === false) {
        throw new RuntimeException('monitor api request failed: ' . $path);
    }
    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) {
        throw new RuntimeException('monitor api invalid json: ' . $path);
    }
    return $decoded;
}

function streamMonitorApiDownload(string $path): void
{
    $baseUrl = monitorApiBaseUrl();
    $url = $baseUrl . $path;
    $headers = [];
    $expectedToken = envValue('V2_API_TOKEN', '');
    if ($expectedToken !== '') {
        $headers[] = 'Authorization: Bearer ' . $expectedToken;
    }
    $context = stream_context_create([
        'http' => [
            'method' => 'GET',
            'header' => implode("\r\n", $headers),
            'ignore_errors' => true,
            'timeout' => 60,
        ],
    ]);
    $raw = @file_get_contents($url, false, $context);
    if ($raw === false) {
        throw new RuntimeException('monitor api download failed: ' . $path);
    }
    $contentType = 'application/octet-stream';
    $contentLength = null;
    $contentDisposition = 'attachment';
    foreach (($http_response_header ?? []) as $headerLine) {
        if (!is_string($headerLine)) {
            continue;
        }
        $lower = strtolower($headerLine);
        if (str_starts_with($lower, 'content-type:')) {
            $contentType = trim(substr($headerLine, strlen('Content-Type:')));
        } elseif (str_starts_with($lower, 'content-length:')) {
            $contentLength = trim(substr($headerLine, strlen('Content-Length:')));
        } elseif (str_starts_with($lower, 'content-disposition:')) {
            $contentDisposition = trim(substr($headerLine, strlen('Content-Disposition:')));
        }
    }
    header('Content-Type: ' . $contentType);
    if ($contentLength !== null && $contentLength !== '') {
        header('Content-Length: ' . $contentLength);
    }
    header('Content-Disposition: ' . $contentDisposition);
    echo $raw;
    exit;
}

function toFloatOrNull($value): ?float
{
    if (is_bool($value)) {
        return null;
    }
    if (is_int($value) || is_float($value)) {
        return (float) $value;
    }
    if (!is_string($value)) {
        return null;
    }
    $trimmed = trim($value);
    if ($trimmed === '') {
        return null;
    }
    if (!is_numeric($trimmed)) {
        return null;
    }
    return (float) $trimmed;
}

function policyConfigForProfile(string $profile): array
{
    $selected = strtolower(trim($profile));
    $base = [
        'policy_version' => 'selection_policy_v1_1',
        'profile' => 'default',
        'weights' => [
            'loss' => 0.55,
            'time' => 0.15,
            'stability' => 0.20,
            'quality' => 0.10,
        ],
        'loss_cap' => 200000.0,
        'time_cap_seconds' => 1800.0,
        'hard_time_limit_seconds' => 3600.0,
        'champion_min_score' => 45.0,
        'champion_margin_min' => 2.0,
    ];

    if (in_array($selected, ['small', 'small_test', 'test'], true)) {
        $base['profile'] = 'small_test';
        $base['weights'] = [
            'loss' => 0.50,
            'time' => 0.20,
            'stability' => 0.20,
            'quality' => 0.10,
        ];
        $base['loss_cap'] = 300000.0;
        $base['time_cap_seconds'] = 900.0;
        $base['hard_time_limit_seconds'] = 1800.0;
        $base['champion_min_score'] = 35.0;
        $base['champion_margin_min'] = 1.0;
        return $base;
    }

    if (in_array($selected, ['real', 'large', 'real_large', 'prod'], true)) {
        $base['profile'] = 'real_large';
        $base['weights'] = [
            'loss' => 0.65,
            'time' => 0.05,
            'stability' => 0.20,
            'quality' => 0.10,
        ];
        $base['loss_cap'] = 200000.0;
        $base['time_cap_seconds'] = 7200.0;
        $base['hard_time_limit_seconds'] = 14400.0;
        $base['champion_min_score'] = 50.0;
        $base['champion_margin_min'] = 3.0;
        return $base;
    }

    return $base;
}

function evaluateProposalSelection(array $proposal, array $policy): array
{
    $status = (string) ($proposal['status'] ?? '');
    $proposalId = (string) ($proposal['proposal_id'] ?? '');
    $sourceRunId = (string) ($proposal['source_run_id'] ?? '');
    $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
    $trainingKpis = is_array($llmMetadata['training_kpis'] ?? null) ? $llmMetadata['training_kpis'] : [];
    $kpiEval = is_array($llmMetadata['kpi_evaluation'] ?? null) ? $llmMetadata['kpi_evaluation'] : [];
    $kpiResult = (string) ($llmMetadata['kpi_result'] ?? '');

    $valLoss = toFloatOrNull($trainingKpis['val_loss_total'] ?? null);
    if ($valLoss === null) {
        $valLoss = toFloatOrNull($kpiEval['val_loss_total'] ?? null);
    }
    $trainingTime = toFloatOrNull($trainingKpis['training_time_seconds'] ?? null);
    if ($trainingTime === null) {
        $trainingTime = toFloatOrNull($llmMetadata['training_time'] ?? null);
    }

    $constraintsFailed = [];
    $allowedStatuses = ['trained', 'accepted', 'validated_phase0'];
    if (!in_array($status, $allowedStatuses, true)) {
        $constraintsFailed[] = 'status_not_allowed';
    }
    if ($valLoss === null) {
        $constraintsFailed[] = 'missing_val_loss_total';
    }
    if ($kpiResult === 'rejected_by_loss') {
        $constraintsFailed[] = 'kpi_rejected';
    }

    $weights = is_array($policy['weights'] ?? null) ? $policy['weights'] : [];
    $wLoss = (float) ($weights['loss'] ?? 0.55);
    $wTime = (float) ($weights['time'] ?? 0.15);
    $wStability = (float) ($weights['stability'] ?? 0.20);
    $wQuality = (float) ($weights['quality'] ?? 0.10);
    $lossCap = (float) ($policy['loss_cap'] ?? 200000.0);
    $timeCap = (float) ($policy['time_cap_seconds'] ?? 1800.0);
    $hardTime = (float) ($policy['hard_time_limit_seconds'] ?? 3600.0);

    $normalizedLoss = 0.0;
    if ($valLoss !== null && $lossCap > 0) {
        $normalizedLoss = max(0.0, 1.0 - min($valLoss, $lossCap) / $lossCap);
    }

    $normalizedTime = 0.5;
    if ($trainingTime !== null && $timeCap > 0) {
        $normalizedTime = max(0.0, 1.0 - min($trainingTime, $timeCap) / $timeCap);
    }

    if ($status === 'trained') {
        $normalizedStability = 1.0;
    } elseif ($status === 'accepted') {
        $normalizedStability = 0.75;
    } else {
        $normalizedStability = 0.55;
    }

    if ($kpiResult === 'promoted') {
        $normalizedQuality = 1.0;
    } elseif ($kpiResult === '') {
        $normalizedQuality = 0.7;
    } else {
        $normalizedQuality = 0.5;
    }

    $rawScore = 100.0 * (
        $wLoss * $normalizedLoss
        + $wTime * $normalizedTime
        + $wStability * $normalizedStability
        + $wQuality * $normalizedQuality
    );

    $penalties = [];
    $finalScore = $rawScore;
    if ($trainingTime !== null && $trainingTime > $hardTime) {
        $penalties[] = ['name' => 'hard_time_limit', 'points' => 15.0];
        $finalScore -= 15.0;
    }
    $finalScore = max(0.0, round($finalScore, 4));

    $eligible = count($constraintsFailed) === 0;
    if (!$eligible) {
        $selectionReason = 'ineligible_due_to_constraints';
    } elseif ($status === 'trained') {
        $selectionReason = 'eligible_trained_candidate';
    } else {
        $selectionReason = 'eligible_pretrained_candidate';
    }

    return [
        'proposal_id' => $proposalId,
        'source_run_id' => $sourceRunId,
        'status' => $status,
        'eligible' => $eligible,
        'score' => $finalScore,
        'selection_reason' => $selectionReason,
        'constraints_failed' => $constraintsFailed,
        'score_breakdown' => [
            'raw_score' => round($rawScore, 4),
            'normalized' => [
                'loss' => round($normalizedLoss, 6),
                'time' => round($normalizedTime, 6),
                'stability' => round($normalizedStability, 6),
                'quality' => round($normalizedQuality, 6),
            ],
            'penalties' => $penalties,
            'metrics_used' => [
                'val_loss_total' => $valLoss,
                'training_time_seconds' => $trainingTime,
                'kpi_result' => $kpiResult,
            ],
        ],
    ];
}

function buildChampionBoard(array $proposals, array $runs, array $policy): array
{
    $latestRunId = '';
    if (count($runs) > 0) {
        $latestRunId = (string) ($runs[0]['run_id'] ?? '');
    }

    $evaluatedGlobal = [];
    foreach ($proposals as $proposal) {
        if (!is_array($proposal)) {
            continue;
        }
        $decision = evaluateProposalSelection($proposal, $policy);
        if ((bool) ($decision['eligible'] ?? false)) {
            $evaluatedGlobal[] = ['proposal' => $proposal, 'decision' => $decision];
        }
    }
    usort($evaluatedGlobal, static function (array $a, array $b): int {
        return ((float) ($b['decision']['score'] ?? 0.0)) <=> ((float) ($a['decision']['score'] ?? 0.0));
    });

    $globalActive = null;
    foreach ($proposals as $proposal) {
        if (!is_array($proposal)) {
            continue;
        }
        $metadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
        if (($metadata['champion_active'] ?? false) === true && (string) ($metadata['champion_scope'] ?? '') === 'global') {
            $globalActive = $proposal;
            break;
        }
    }

    $globalChampion = null;
    if ($globalActive !== null) {
        foreach ($evaluatedGlobal as $entry) {
            if ((string) ($entry['proposal']['proposal_id'] ?? '') === (string) ($globalActive['proposal_id'] ?? '')) {
                $globalChampion = $entry;
                break;
            }
        }
    }
    if ($globalChampion === null && count($evaluatedGlobal) > 0) {
        $globalChampion = $evaluatedGlobal[0];
    }

    $evaluatedRun = [];
    if ($latestRunId !== '') {
        foreach ($evaluatedGlobal as $entry) {
            if ((string) ($entry['proposal']['source_run_id'] ?? '') === $latestRunId) {
                $evaluatedRun[] = $entry;
            }
        }
    }
    usort($evaluatedRun, static function (array $a, array $b): int {
        return ((float) ($b['decision']['score'] ?? 0.0)) <=> ((float) ($a['decision']['score'] ?? 0.0));
    });

    $runActive = null;
    foreach ($proposals as $proposal) {
        if (!is_array($proposal) || $latestRunId === '') {
            continue;
        }
        if ((string) ($proposal['source_run_id'] ?? '') !== $latestRunId) {
            continue;
        }
        $metadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
        if (($metadata['champion_active'] ?? false) === true && (string) ($metadata['champion_scope'] ?? '') === 'run') {
            $runActive = $proposal;
            break;
        }
    }

    $runChampion = null;
    if ($runActive !== null) {
        foreach ($evaluatedRun as $entry) {
            if ((string) ($entry['proposal']['proposal_id'] ?? '') === (string) ($runActive['proposal_id'] ?? '')) {
                $runChampion = $entry;
                break;
            }
        }
    }
    if ($runChampion === null && count($evaluatedRun) > 0) {
        $runChampion = $evaluatedRun[0];
    }

    $topN = 5;
    $globalTop = array_slice($evaluatedGlobal, 0, $topN + 1);
    $runTop = array_slice($evaluatedRun, 0, $topN + 1);

    return [
        'latest_run_id' => $latestRunId,
        'policy_version' => (string) ($policy['policy_version'] ?? 'selection_policy_v1_1'),
        'policy_profile' => (string) ($policy['profile'] ?? 'default'),
        'champion_global' => $globalChampion,
        'champion_run' => $runChampion,
        'global_top' => $globalTop,
        'run_top' => $runTop,
    ];
}

loadDotEnvFiles([
    getenv('V2_DOTENV_PATH') ?: '',
    __DIR__ . '/../.env',
    __DIR__ . '/../../.env',
]);

ensureMonitorSessionIfConfigured();

try {
    $service = new ApiService(buildStore());
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && (string) ($_POST['action'] ?? '') === 'proposal_status') {
        $proposalId = is_string($_POST['proposal_id'] ?? null) ? (string) $_POST['proposal_id'] : '';
        $status = is_string($_POST['status'] ?? null) ? (string) $_POST['status'] : '';
        if ($proposalId !== '' && $status !== '') {
            $service->updateModelProposalStatus($proposalId, $status);
        }
        redirectToMonitorHome();
    }
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && (string) ($_POST['action'] ?? '') === 'proposal_enqueue_phase0') {
        $proposalId = is_string($_POST['proposal_id'] ?? null) ? (string) $_POST['proposal_id'] : '';
        if ($proposalId !== '') {
            $service->enqueueModelProposalPhase0($proposalId);
        }
        redirectToMonitorHome();
    }
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && (string) ($_POST['action'] ?? '') === 'evaluate_kpis') {
        $threshold = is_numeric($_POST['threshold'] ?? null) ? (float) $_POST['threshold'] : 0.5;
        $_SESSION['eval_result'] = $service->evaluateModelProposalsKpis($threshold);
        redirectToMonitorHome();
    }
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && (string) ($_POST['action'] ?? '') === 'reset_all_data') {
        $confirm = is_string($_POST['confirm'] ?? null) ? (string) $_POST['confirm'] : '';
        if ($confirm === 'DELETE TEST DATA') {
            $preserveBestModels = in_array((string) ($_POST['preserve_best_models'] ?? '0'), ['1', 'true', 'yes'], true);
            $_SESSION['reset_result'] = $service->resetAllData($preserveBestModels, 3);
        }
        redirectToMonitorHome();
    }
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && (string) ($_POST['action'] ?? '') === 'toggle_auto_refresh') {
        $_SESSION['monitor_auto_refresh'] = in_array((string) ($_POST['enabled'] ?? '1'), ['1', 'true', 'yes'], true);
        redirectToMonitorHome();
    }
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && (string) ($_POST['action'] ?? '') === 'execution_request_update_limits') {
        $requestId = is_string($_POST['request_id'] ?? null) ? (string) $_POST['request_id'] : '';
        if ($requestId !== '') {
            $_SESSION['execution_limits_result'] = $service->updateExecutionRequestConfig($requestId, [
                'max_epochs' => is_numeric($_POST['max_epochs'] ?? null) ? (int) $_POST['max_epochs'] : 0,
                'max_training_seconds' => is_numeric($_POST['max_training_seconds'] ?? null) ? (int) $_POST['max_training_seconds'] : 0,
            ]);
        }
        redirectToMonitorHome();
    }
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && (string) ($_POST['action'] ?? '') === 'execution_request_create') {
        $requestType = is_string($_POST['request_type'] ?? null) ? (string) $_POST['request_type'] : 'smoke_run';
        $config = [
            'profile' => is_string($_POST['profile'] ?? null) ? (string) $_POST['profile'] : 'small_test',
            'generations' => is_numeric($_POST['generations'] ?? null) ? (int) $_POST['generations'] : 1,
            'models_per_generation' => is_numeric($_POST['models_per_generation'] ?? null) ? (int) $_POST['models_per_generation'] : 1,
            'max_epochs' => is_numeric($_POST['max_epochs'] ?? null) ? (int) $_POST['max_epochs'] : 0,
            'max_training_seconds' => is_numeric($_POST['max_training_seconds'] ?? null) ? (int) $_POST['max_training_seconds'] : 0,
            'champion_scope' => is_string($_POST['champion_scope'] ?? null) ? (string) $_POST['champion_scope'] : 'run',
            'auto_feed' => in_array((string) ($_POST['auto_feed'] ?? '1'), ['1', 'true', 'yes'], true),
            'resume_enabled' => in_array((string) ($_POST['resume_enabled'] ?? '1'), ['1', 'true', 'yes'], true),
            'bootstrap_seed_model_if_empty' => in_array((string) ($_POST['bootstrap_seed_model_if_empty'] ?? '0'), ['1', 'true', 'yes'], true),
            'auto_process_proposals_phase0' => in_array((string) ($_POST['auto_process_proposals_phase0'] ?? '1'), ['1', 'true', 'yes'], true),
            'llm_min_interval_seconds' => is_numeric($_POST['llm_min_interval_seconds'] ?? null) ? (int) $_POST['llm_min_interval_seconds'] : 20,
        ];
        $service->createExecutionRequest($requestType, $config);
        redirectToMonitorHome();
    }
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && (string) ($_POST['action'] ?? '') === 'execution_request_cancel') {
        $requestId = is_string($_POST['request_id'] ?? null) ? (string) $_POST['request_id'] : '';
        if ($requestId !== '') {
            $service->cancelExecutionRequest($requestId);
        }
        redirectToMonitorHome();
    }
    $summaryRunId = is_string($_GET['summary_run_id'] ?? null) ? (string) $_GET['summary_run_id'] : '';
    if ($summaryRunId !== '') {
        $summary = monitorApiRequest('/runs/' . rawurlencode($summaryRunId) . '/summary');
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($summary, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit;
    }
    $timelineRunId = is_string($_GET['timeline_run_id'] ?? null) ? (string) $_GET['timeline_run_id'] : '';
    if ($timelineRunId !== '') {
        $timeline = monitorApiRequest('/runs/' . rawurlencode($timelineRunId) . '/timeline?limit=200');
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($timeline, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit;
    }
    $executionAutopsyId = is_string($_GET['execution_autopsy_id'] ?? null) ? (string) $_GET['execution_autopsy_id'] : '';
    if ($executionAutopsyId !== '') {
        $autopsy = monitorApiRequest('/execution-requests/' . rawurlencode($executionAutopsyId) . '/autopsy?timeline_limit=40');
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($autopsy, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit;
    }
    $downloadArtifactId = is_string($_GET['download_artifact_id'] ?? null) ? (string) $_GET['download_artifact_id'] : '';
    if ($downloadArtifactId !== '') {
        streamMonitorApiDownload('/artifacts/' . rawurlencode($downloadArtifactId) . '/download');
    }
    $compareLeft = is_string($_GET['compare_left'] ?? null) ? (string) $_GET['compare_left'] : '';
    $compareRight = is_string($_GET['compare_right'] ?? null) ? (string) $_GET['compare_right'] : '';
    $comparison = null;
    if ($compareLeft !== '' && $compareRight !== '') {
        $comparison = monitorApiRequest('/models/compare?left=' . rawurlencode($compareLeft) . '&right=' . rawurlencode($compareRight));
    }
    $proposalId = is_string($_GET['proposal_id'] ?? null) ? (string) $_GET['proposal_id'] : '';
    if ($proposalId !== '') {
        $proposal = monitorApiRequest('/models/' . rawurlencode($proposalId) . '/detail-view');
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($proposal, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit;
    }
    $runsPayload = monitorApiRequest('/runs?limit=100');
    $executionRequestsPayload = monitorApiRequest('/execution-requests?limit=100');
    $proposalsPayload = monitorApiRequest('/proposals?limit=100');
    $recentEventsPayload = monitorApiRequest('/events?limit=15');
    $recentMetricsPayload = monitorApiRequest('/metrics?limit=50');
    $globalChampionPayload = monitorApiRequest('/champion/global?top_n=5');
    $shortlistPayload = monitorApiRequest('/models/shortlist?limit=5');

    $runs = is_array($runsPayload['runs'] ?? null) ? $runsPayload['runs'] : [];
    $executionRequests = is_array($executionRequestsPayload['execution_requests'] ?? null) ? $executionRequestsPayload['execution_requests'] : [];
    $proposals = is_array($proposalsPayload['proposals'] ?? null) ? $proposalsPayload['proposals'] : [];
    $runsById = [];
    foreach ($runs as $run) {
        if (is_array($run) && (string) ($run['run_id'] ?? '') !== '') {
            $runsById[(string) $run['run_id']] = $run;
        }
    }
    $recentEvents = is_array($recentEventsPayload['events'] ?? null) ? $recentEventsPayload['events'] : [];
    $recentMetrics = is_array($recentMetricsPayload['metrics'] ?? null) ? $recentMetricsPayload['metrics'] : [];
    $latestRunId = count($runs) > 0 ? (string) ($runs[0]['run_id'] ?? '') : '';
    $runChampionPayload = $latestRunId !== '' ? monitorApiRequest('/champion/run/' . rawurlencode($latestRunId) . '?top_n=5') : ['champion' => null, 'top_candidates' => []];
    $referencesPayload = $latestRunId !== '' ? monitorApiRequest('/runs/' . rawurlencode($latestRunId) . '/references?limit=10') : ['references' => []];
    $runSummaryPayload = $latestRunId !== '' ? monitorApiRequest('/runs/' . rawurlencode($latestRunId) . '/summary') : [];
    $championBoard = [
        'latest_run_id' => $latestRunId,
        'policy_version' => (string) ($globalChampionPayload['policy_version'] ?? ''),
        'policy_profile' => (string) ($globalChampionPayload['policy_profile'] ?? ''),
        'champion_global' => $globalChampionPayload['champion'] ?? null,
        'champion_run' => $runChampionPayload['champion'] ?? null,
        'global_top' => is_array($globalChampionPayload['top_candidates'] ?? null) ? $globalChampionPayload['top_candidates'] : [],
        'run_top' => is_array($runChampionPayload['top_candidates'] ?? null) ? $runChampionPayload['top_candidates'] : [],
    ];
    $modelShortlist = is_array($shortlistPayload['shortlist'] ?? null) ? $shortlistPayload['shortlist'] : [];
    $referenceModels = is_array($referencesPayload['references'] ?? null) ? $referencesPayload['references'] : [];
    $runSummary = is_array($runSummaryPayload) ? $runSummaryPayload : [];
    $compareCandidateA = count($modelShortlist) > 0 && is_array($modelShortlist[0]) ? (string) ($modelShortlist[0]['proposal_id'] ?? '') : '';
    $compareCandidateB = count($modelShortlist) > 1 && is_array($modelShortlist[1]) ? (string) ($modelShortlist[1]['proposal_id'] ?? '') : '';
    if (!isset($_SESSION['monitor_auto_refresh'])) {
        $_SESSION['monitor_auto_refresh'] = true;
    }
    $autoRefreshEnabled = ($_SESSION['monitor_auto_refresh'] ?? true) === true;
} catch (Throwable $error) {
    http_response_code(500);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'monitor_error: ' . $error->getMessage();
    exit;
}
?>
<!doctype html>
<html lang="ca">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <?php if ($autoRefreshEnabled): ?>
    <meta http-equiv="refresh" content="30">
    <?php endif; ?>
    <title>V2 Monitor</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 20px; }
        h1 { margin: 0 0 16px 0; }
        .meta { color: #94a3b8; margin-bottom: 16px; }
        table { width: 100%; border-collapse: collapse; background: #111827; }
        th, td { padding: 10px; border-bottom: 1px solid #1f2937; text-align: left; font-size: 14px; }
        th { color: #93c5fd; font-weight: 600; }
        a { color: #93c5fd; text-decoration: none; }
        .status-completed { color: #86efac; }
        .status-running { color: #facc15; }
        .status-failed { color: #fca5a5; }
        .status-draft { color: #fde68a; }
        .status-queued_phase0 { color: #c4b5fd; }
        .status-validated_phase0 { color: #93c5fd; }
        .status-accepted { color: #86efac; }
        .status-rejected { color: #fca5a5; }
        h2 { margin: 24px 0 12px 0; }
        .panel { background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 12px; margin-bottom: 16px; }
        .panel-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; margin-bottom: 12px; }
        .kpi { font-size: 13px; color: #cbd5e1; }
        .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
        form { margin: 0; }
        .toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
        .danger { border-color: #ef4444; color: #fecaca; }
        .notice { color: #93c5fd; }
        select, button, input { background: #0b1220; color: #e2e8f0; border: 1px solid #334155; padding: 4px 6px; border-radius: 4px; }
        .section-header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin: 24px 0 12px 0; }
        .section-header h2 { margin: 0; }
        .form-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:16px; }
        .field-card { background:#0b1220; border:1px solid #1f2937; border-radius:8px; padding:10px; }
        .field-card label { display:block; }
        .field-help { display:block; margin-top:6px; color:#94a3b8; font-size:12px; line-height:1.35; }
        .plan-summary { background:#0b1220; border:1px solid #334155; border-radius:8px; padding:12px; margin-bottom:12px; }
        .plan-summary strong { color:#f8fafc; }
        .stack { display:flex; flex-direction:column; gap:8px; }
        .badge-row { display:flex; flex-wrap:wrap; gap:6px; }
        .badge { display:inline-flex; align-items:center; gap:4px; border-radius:999px; padding:3px 8px; font-size:12px; font-weight:600; border:1px solid transparent; }
        .badge-warning { background:#422006; color:#fde68a; border-color:#92400e; }
        .badge-danger { background:#3f1518; color:#fecaca; border-color:#b91c1c; }
        .badge-muted { background:#172033; color:#cbd5e1; border-color:#475569; }
        .badge-success { background:#052e16; color:#bbf7d0; border-color:#166534; }
        .status-pill { display:inline-block; padding:4px 8px; border-radius:999px; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.03em; }
        .status-pill-completed { background:#052e16; color:#bbf7d0; }
        .status-pill-running { background:#422006; color:#fde68a; }
        .status-pill-failed { background:#3f1518; color:#fecaca; }
        .status-pill-cancelled { background:#172033; color:#cbd5e1; }
        .status-pill-pending, .status-pill-claimed { background:#1e293b; color:#bfdbfe; }
        .inline-actions { display:flex; flex-wrap:wrap; gap:8px; }
        .summary-card { background:#0b1220; border:1px solid #1f2937; border-radius:8px; padding:10px; }
        .summary-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:8px; }
        .summary-label { color:#94a3b8; font-size:12px; margin-bottom:3px; }
    </style>
</head>
<body>
    <h1>V2 Monitor</h1>
    <?php 
        $resetResult = is_array($_SESSION['reset_result'] ?? null) ? $_SESSION['reset_result'] : null; unset($_SESSION['reset_result']); 
        $evalResult = is_array($_SESSION['eval_result'] ?? null) ? $_SESSION['eval_result'] : null; unset($_SESSION['eval_result']); 
        $showResetConfirm = (string) ($_GET['confirm_reset'] ?? '') === '1';
        $limitsResult = is_array($_SESSION['execution_limits_result'] ?? null) ? $_SESSION['execution_limits_result'] : null; unset($_SESSION['execution_limits_result']);
    ?>
    <div class="meta">Actualització automàtica <?php echo $autoRefreshEnabled ? 'activada (30s)' : 'desactivada'; ?> · Runs: <?php echo count($runs); ?> · <a href="./monitor.php?logout=1">Sortir</a></div>
    <div class="meta">Selection policy: <span class="mono"><?php echo htmlspecialchars((string) ($championBoard['policy_version'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span> · profile: <span class="mono"><?php echo htmlspecialchars((string) ($championBoard['policy_profile'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
    <div class="toolbar">
        <form method="post" action="./monitor.php">
            <input type="hidden" name="action" value="evaluate_kpis">
            <input type="number" name="threshold" value="0.5" step="0.01" style="width: 70px;">
            <button type="submit">Avaluar KPIs (promoure models)</button>
        </form>
        <form method="get" action="./monitor.php">
            <input type="hidden" name="confirm_reset" value="1">
            <button type="submit" class="danger">Reset dades prova</button>
        </form>
        <form method="post" action="./monitor.php">
            <input type="hidden" name="action" value="toggle_auto_refresh">
            <input type="hidden" name="enabled" value="<?php echo $autoRefreshEnabled ? '0' : '1'; ?>">
            <button type="submit"><?php echo $autoRefreshEnabled ? 'Aturar auto-actualització' : 'Activar auto-actualització'; ?></button>
        </form>
        <?php if ($resetResult !== null): ?>
            <span class="notice">Reset fet · Runs: <?php echo (int) ($resetResult['deleted']['runs'] ?? 0); ?> · Events: <?php echo (int) ($resetResult['deleted']['events'] ?? 0); ?> · Metrics: <?php echo (int) ($resetResult['deleted']['metrics'] ?? 0); ?> · Artifacts: <?php echo (int) ($resetResult['deleted']['artifacts'] ?? 0); ?> · Proposals: <?php echo (int) ($resetResult['deleted']['model_proposals'] ?? 0); ?> · Exec requests: <?php echo (int) ($resetResult['deleted']['execution_requests'] ?? 0); ?> · Fitxers artifact: <?php echo (int) ($resetResult['deleted']['artifact_files'] ?? 0); ?><?php if (($resetResult['preserve_best_models'] ?? false) === true): ?> · Conservats: <?php echo (int) (($resetResult['preserved']['model_proposals'] ?? 0)); ?> models top<?php endif; ?></span>
        <?php endif; ?>
        <?php if ($evalResult !== null): ?>
            <span class="notice">Models avaluats (KPIs): <?php echo (int) ($evalResult['evaluated_count'] ?? 0); ?></span>
        <?php endif; ?>
        <?php if ($limitsResult !== null): ?>
            <span class="notice">Límits actualitzats per <span class="mono"><?php echo htmlspecialchars((string) ($limitsResult['request_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span> · max_epochs=<?php echo (int) (($limitsResult['config']['max_epochs'] ?? 0)); ?> · max_training_seconds=<?php echo (int) (($limitsResult['config']['max_training_seconds'] ?? 0)); ?>s</span>
        <?php endif; ?>
    </div>

    <?php if ($showResetConfirm): ?>
    <div class="panel danger" style="margin-top:0;">
        <h2 style="margin-top:0; color:#fecaca;">Confirmar reset de dades de prova</h2>
        <div class="kpi">Aquesta acció esborra totes les dades guardades al servidor per fer proves netes: runs, events, metrics, artifacts, proposals, execution requests i fitxers d'artifacts del servidor.</div>
        <div class="kpi" style="margin-top:8px;">Opcionalment pots conservar els millors models entrenats actuals com a mostra per a la següent execució.</div>
        <div class="kpi" style="margin-top:8px;">Per confirmar, escriu exactament <span class="mono">DELETE TEST DATA</span>.</div>
        <form method="post" action="./monitor.php" style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:12px;">
            <input type="hidden" name="action" value="reset_all_data">
            <input type="text" name="confirm" placeholder="DELETE TEST DATA" class="mono" style="min-width:220px; background:#0b1220; color:#e2e8f0; border:1px solid #7f1d1d; padding:6px 8px; border-radius:4px;">
            <label class="kpi" style="display:flex; align-items:center; gap:6px;"><input type="checkbox" name="preserve_best_models" value="1"> Conservar millors models</label>
            <button type="submit" class="danger">Confirmar esborrat</button>
            <a href="./monitor.php">Cancel·lar</a>
        </form>
    </div>
    <?php endif; ?>

    <div class="section-header">
        <h2>Nova execució</h2>
        <span class="kpi">Entén el pla abans d’executar-lo al worker.</span>
    </div>
    <div class="panel">
        <form method="post" action="./monitor.php" id="execution-create-form">
            <input type="hidden" name="action" value="execution_request_create">
            <div class="form-grid">
                <div class="field-card"><label class="kpi">Tipus<br><select name="request_type" id="request_type"><option value="smoke_run">smoke_run</option><option value="micro_training">micro_training</option><option value="integration_matrix">integration_matrix</option><option value="resume_training">resume_training</option><option value="cleanup">cleanup</option></select><span class="field-help" id="request_type_help">Prova ràpida end-to-end.</span></label></div>
                <div class="field-card"><label class="kpi">Perfil<br><select name="profile" id="profile"><option value="small_test">small_test</option><option value="default">default</option><option value="real_large">real_large</option></select><span class="field-help" id="profile_help">Execució ràpida per validar pipeline i control operatiu.</span></label></div>
                <div class="field-card"><label class="kpi">Generacions<br><input type="number" name="generations" id="generations" value="1" min="1" style="width:70px;"><span class="field-help">Nombre de cicles complets (generar + entrenar models)</span></label></div>
                <div class="field-card"><label class="kpi">Models / generació<br><input type="number" name="models_per_generation" id="models_per_generation" value="1" min="1" style="width:70px;"><span class="field-help">Nombre de models nous que es generaran per cada generació</span></label></div>
                <div class="field-card"><label class="kpi">Límit d'èpoques<br><input type="number" name="max_epochs" id="max_epochs" value="0" min="0" style="width:70px;"><span class="field-help">Nombre màxim d’èpoques per entrenament (0 = usar la definició del model)</span></label></div>
                <div class="field-card"><label class="kpi">Límit de temps<br><input type="number" name="max_training_seconds" id="max_training_seconds" value="0" min="0" style="width:70px;"><span class="field-help">Temps màxim per entrenament en segons (0 = sense límit extra)</span></label></div>
                <div class="field-card"><label class="kpi">Champion scope<br><select name="champion_scope" id="champion_scope"><option value="run">run</option><option value="global">global</option></select><span class="field-help">Defineix si el champion es decideix dins del run o globalment</span></label></div>
                <div class="field-card"><label class="kpi">Auto-feed<br><select name="auto_feed" id="auto_feed"><option value="1">on</option><option value="0">off</option></select><span class="field-help">Permet que el sistema generi nous models automàticament</span></label></div>
                <div class="field-card"><label class="kpi">Resume<br><select name="resume_enabled" id="resume_enabled"><option value="1">on</option><option value="0">off</option></select><span class="field-help">Permet reprendre entrenaments interromputs des de checkpoint</span></label></div>
                <div class="field-card"><label class="kpi">Seed inicial<br><select name="bootstrap_seed_model_if_empty" id="bootstrap_seed_model_if_empty"><option value="0">off</option><option value="1">on</option></select><span class="field-help">Crea un model inicial si no n’hi ha cap disponible</span></label></div>
                <div class="field-card"><label class="kpi">Auto phase0<br><select name="auto_process_proposals_phase0" id="auto_process_proposals_phase0"><option value="1">on</option><option value="0">off</option></select><span class="field-help">Processa automàticament les propostes inicials abans d’entrenar</span></label></div>
                <div class="field-card"><label class="kpi">LLM interval<br><input type="number" name="llm_min_interval_seconds" id="llm_min_interval_seconds" value="30" min="0" style="width:70px;"><span class="field-help">Temps mínim entre crides al LLM per evitar saturació</span></label></div>
            </div>
            <div class="plan-summary" id="execution-plan-summary">
                <div><strong id="plan-total-models">1 generació × 1 model = 1 model total</strong></div>
                <div class="kpi" id="plan-profile-line">Perfil small_test · Execució ràpida per validar pipeline i control operatiu.</div>
                <div class="kpi" id="plan-type-line">Tipus smoke_run · Prova ràpida end-to-end.</div>
                <div class="kpi" id="plan-options-line">Resume activat · champion run</div>
                <div class="kpi" id="plan-limits-line">Límits: epochs model · temps lliure</div>
                <div class="kpi" id="plan-duration-line">Estimació de durada: 4 min</div>
            </div>
            <div class="inline-actions"><button type="submit">Crear execució</button></div>
        </form>
        <div class="kpi">Què fa: el servidor crea el pla, el worker de Colab el reclama i executa el cicle complet sense tocar scripts manuals.</div>
        <div class="kpi">Auto-feed: si la cua queda buida, el supervisor pot generar feina nova. Resume: intenta reprendre entrenaments amb checkpoints compatibles.</div>
    </div>

    <div class="section-header">
        <h2>Execucions actives i recents</h2>
        <span class="kpi">Veu alertes, resultat final i repeteix configuracions útils.</span>
    </div>
    <div class="panel">
        <table>
            <thead>
                <tr>
                    <th>Request</th>
                    <th>Type</th>
                    <th>Description</th>
                    <th>Status</th>
                    <th>Plan</th>
                    <th>Config</th>
                    <th>Progress</th>
                    <th>Run IDs</th>
                    <th>Stage</th>
                    <th>Timing</th>
                    <th>Worker</th>
                    <th>Heartbeat</th>
                    <th>Attempts</th>
                    <th>Reference</th>
                    <th>Result</th>
                    <th>Autòpsia</th>
                    <th>Acció</th>
                </tr>
            </thead>
            <tbody>
            <?php foreach ($executionRequests as $request): ?>
                <?php if (!is_array($request)) { continue; } ?>
                <?php $reqId = (string) ($request['request_id'] ?? ''); ?>
                <?php $requestConfig = is_array($request['config'] ?? null) ? $request['config'] : []; ?>
                <?php $inferredRunId = inferExecutionRunId($request, $latestRunId); ?>
                <?php $requestProgress = inferExecutionProgress($request, $inferredRunId, $runsById, $proposals); ?>
                <?php $requestRunIds = is_array($request['run_ids'] ?? null) ? $request['run_ids'] : []; ?>
                <?php if ($inferredRunId !== '' && !in_array($inferredRunId, $requestRunIds, true)) { array_unshift($requestRunIds, $inferredRunId); } ?>
                <?php $requestResultSummary = is_array($request['result_summary'] ?? null) ? $request['result_summary'] : []; ?>
                <?php if ($inferredRunId !== '' && ($requestResultSummary['run_id'] ?? '') === '') { $requestResultSummary['run_id'] = $inferredRunId; } ?>
                <?php $championEventType = (string) ($requestResultSummary['latest_event_type'] ?? ''); ?>
                <?php $repairSummary = executionRepairSummary($requestResultSummary); ?>
                <?php $estimatedMinutes = estimateExecutionDurationMinutes($requestConfig); ?>
                <?php $elapsedLabel = formatDurationShort($request['elapsed_seconds'] ?? null); ?>
                <?php $alertBadges = requestAlertBadges($request); ?>
                <?php $statusValue = (string) ($request['status'] ?? ''); ?>
                <?php $statusClass = 'status-pill status-pill-' . htmlspecialchars($statusValue, ENT_QUOTES, 'UTF-8'); ?>
                <?php $artifactAvailability = artifactAvailabilityLabel($requestResultSummary); ?>
                <tr>
                    <td class="mono"><?php echo htmlspecialchars($reqId, ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($request['type'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($request['type_description'] ?? ''), ENT_QUOTES, 'UTF-8'); ?><br><span class="kpi"><?php echo htmlspecialchars(requestTypeExplanation((string) ($request['type'] ?? '')), ENT_QUOTES, 'UTF-8'); ?></span></td>
                    <td><span class="<?php echo $statusClass; ?>"><?php echo htmlspecialchars($statusValue, ENT_QUOTES, 'UTF-8'); ?></span><?php if (!empty($alertBadges)): ?><div class="badge-row" style="margin-top:6px;"><?php foreach ($alertBadges as $badge): ?><span class="badge <?php echo htmlspecialchars((string) ($badge['class'] ?? ''), ENT_QUOTES, 'UTF-8'); ?>"><?php echo htmlspecialchars((string) ($badge['label'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span><?php endforeach; ?></div><?php endif; ?></td>
                    <td><?php echo htmlspecialchars((string) (($requestConfig['generations'] ?? 1) . ' gen · ' . ($requestConfig['models_per_generation'] ?? 1) . ' models/gen'), ENT_QUOTES, 'UTF-8'); ?><br><span class="kpi"><?php echo htmlspecialchars(executionProfileExplanation((string) ($requestConfig['profile'] ?? 'small_test')), ENT_QUOTES, 'UTF-8'); ?></span><br><span class="kpi">epochs=<?php echo htmlspecialchars((string) ($requestConfig['max_epochs'] ?? 0), ENT_QUOTES, 'UTF-8'); ?> · max_s=<?php echo htmlspecialchars((string) ($requestConfig['max_training_seconds'] ?? 0), ENT_QUOTES, 'UTF-8'); ?></span></td>
                    <td><details><summary>Veure</summary><pre style="font-size:11px; margin:0; background:#1e293b; padding:4px; overflow-x:auto;"><?php echo htmlspecialchars(json_encode($requestConfig, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE), ENT_QUOTES, 'UTF-8'); ?></pre></details></td>
                    <td><?php echo htmlspecialchars((string) (($requestProgress['generations_completed'] ?? 0) . '/' . ($requestProgress['generations_total'] ?? 0)), ENT_QUOTES, 'UTF-8'); ?> · models=<?php echo htmlspecialchars((string) ($requestProgress['models_generated'] ?? 0), ENT_QUOTES, 'UTF-8'); ?>/<?php echo htmlspecialchars((string) ($requestProgress['models_trained'] ?? 0), ENT_QUOTES, 'UTF-8'); ?><br><span class="kpi"><?php echo htmlspecialchars((string) ($requestProgress['progress_percent'] ?? 0), ENT_QUOTES, 'UTF-8'); ?>% completat</span></td>
                    <td><?php echo htmlspecialchars($inferredRunId, ENT_QUOTES, 'UTF-8'); ?><br><span class="kpi mono"><?php echo htmlspecialchars(implode(', ', array_slice(array_map('strval', $requestRunIds), 0, 3)), ENT_QUOTES, 'UTF-8'); ?></span></td>
                    <td><?php echo htmlspecialchars((string) (($request['current_stage_label'] ?? '') ?: ($request['current_stage'] ?? '')), ENT_QUOTES, 'UTF-8'); ?><br><span class="kpi"><?php echo htmlspecialchars((string) (($requestResultSummary['latest_event_type'] ?? '') ?: ($requestResultSummary['latest_artifact_type'] ?? '')), ENT_QUOTES, 'UTF-8'); ?></span></td>
                    <td>estimació <?php echo htmlspecialchars((string) $estimatedMinutes, ENT_QUOTES, 'UTF-8'); ?> min<br><span class="kpi">elapsed <?php echo htmlspecialchars($elapsedLabel, ENT_QUOTES, 'UTF-8'); ?></span></td>
                    <td><?php echo htmlspecialchars((string) ($request['claimed_by_worker'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($request['heartbeat_at'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($request['attempts'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars(executionReferenceSummary($requestResultSummary), ENT_QUOTES, 'UTF-8'); ?><br><span class="kpi"><?php echo htmlspecialchars((string) (($requestResultSummary['reference_context']['reference_models_count'] ?? 0) . ' refs'), ENT_QUOTES, 'UTF-8'); ?></span></td>
                    <td>
                        <?php if (in_array($statusValue, ['completed', 'failed', 'cancelled'], true)): ?>
                            <div class="summary-card stack">
                                <div class="summary-grid">
                                    <div><div class="summary-label">Estat final</div><div><?php echo htmlspecialchars($statusValue, ENT_QUOTES, 'UTF-8'); ?></div></div>
                                    <div><div class="summary-label">Champion</div><div><?php echo htmlspecialchars(championOutcomeExplanation($championEventType), ENT_QUOTES, 'UTF-8'); ?></div></div>
                                    <div><div class="summary-label">Models</div><div><?php echo htmlspecialchars((string) (($requestProgress['models_generated'] ?? 0) . ' generats · ' . ($requestProgress['models_trained'] ?? 0) . ' entrenats'), ENT_QUOTES, 'UTF-8'); ?></div></div>
                                    <div><div class="summary-label">Artifact final</div><div><?php echo htmlspecialchars($artifactAvailability, ENT_QUOTES, 'UTF-8'); ?></div></div>
                                </div>
                                <div class="kpi">run_ids: <span class="mono"><?php echo htmlspecialchars(implode(', ', array_map('strval', $requestRunIds)), ENT_QUOTES, 'UTF-8'); ?></span></div>
                                <div class="kpi">proposal final: <span class="mono"><?php echo htmlspecialchars((string) ($requestResultSummary['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
                                <?php if ($repairSummary !== ''): ?><div class="kpi"><?php echo htmlspecialchars($repairSummary, ENT_QUOTES, 'UTF-8'); ?></div><?php endif; ?>
                            </div>
                        <?php else: ?>
                            <?php echo htmlspecialchars(championOutcomeExplanation($championEventType), ENT_QUOTES, 'UTF-8'); ?><br><span class="kpi mono"><?php echo htmlspecialchars((string) ($requestResultSummary['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span><?php if ($repairSummary !== ''): ?><br><span class="kpi"><?php echo htmlspecialchars($repairSummary, ENT_QUOTES, 'UTF-8'); ?></span><?php endif; ?>
                        <?php endif; ?>
                        <details><summary>Veure</summary><pre style="font-size:11px; margin:0; background:#1e293b; padding:4px; overflow-x:auto;"><?php echo htmlspecialchars(json_encode($requestResultSummary, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE), ENT_QUOTES, 'UTF-8'); ?></pre></details>
                    </td>
                    <td><a href="./monitor.php?execution_autopsy_id=<?php echo rawurlencode($reqId); ?>" target="_blank" rel="noreferrer">Veure</a></td>
                    <td>
                        <div class="inline-actions">
                        <form method="post" action="./monitor.php">
                            <?php echo hiddenConfigInputs((string) ($request['type'] ?? ''), $requestConfig); ?>
                            <button type="submit">Re-executar</button>
                        </form>
                        <form method="post" action="./monitor.php">
                            <?php echo hiddenConfigInputs((string) ($request['type'] ?? ''), $requestConfig); ?>
                            <button type="submit">Executar de nou amb mateix config</button>
                        </form>
                        <?php if (in_array((string) ($request['status'] ?? ''), ['pending', 'claimed', 'running'], true)): ?>
                            <form method="post" action="./monitor.php" class="inline-actions">
                                <input type="hidden" name="action" value="execution_request_update_limits">
                                <input type="hidden" name="request_id" value="<?php echo htmlspecialchars($reqId, ENT_QUOTES, 'UTF-8'); ?>">
                                <input type="number" name="max_epochs" value="<?php echo htmlspecialchars((string) ($requestConfig['max_epochs'] ?? 0), ENT_QUOTES, 'UTF-8'); ?>" min="0" style="width:72px;" title="Límit d'èpoques">
                                <input type="number" name="max_training_seconds" value="<?php echo htmlspecialchars((string) ($requestConfig['max_training_seconds'] ?? 0), ENT_QUOTES, 'UTF-8'); ?>" min="0" style="width:86px;" title="Límit de temps">
                                <button type="submit">Aplicar límits</button>
                            </form>
                        <?php endif; ?>
                        <?php if (in_array((string) ($request['status'] ?? ''), ['pending', 'claimed', 'running'], true)): ?>
                            <form method="post" action="./monitor.php">
                                <input type="hidden" name="action" value="execution_request_cancel">
                                <input type="hidden" name="request_id" value="<?php echo htmlspecialchars($reqId, ENT_QUOTES, 'UTF-8'); ?>">
                                <button type="submit">Cancel·lar</button>
                            </form>
                        <?php endif; ?>
                        </div>
                    </td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>

    <h2>Run Summary</h2>
    <div class="panel">
        <?php $runCounts = is_array($runSummary['counts'] ?? null) ? $runSummary['counts'] : []; ?>
        <?php $runProposalCounts = is_array($runSummary['proposals_by_status'] ?? null) ? $runSummary['proposals_by_status'] : []; ?>
        <?php $runChampionSummary = is_array($runSummary['champion'] ?? null) ? $runSummary['champion'] : []; ?>
        <div class="kpi">latest_run_id: <span class="mono"><?php echo htmlspecialchars((string) ($championBoard['latest_run_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
        <div class="kpi">events=<?php echo (int) ($runCounts['events'] ?? 0); ?> · metrics=<?php echo (int) ($runCounts['metrics'] ?? 0); ?> · artifacts=<?php echo (int) ($runCounts['artifacts'] ?? 0); ?> · proposals=<?php echo (int) ($runCounts['proposals'] ?? 0); ?></div>
        <div class="kpi">trained=<?php echo (int) ($runProposalCounts['trained'] ?? 0); ?> · accepted=<?php echo (int) ($runProposalCounts['accepted'] ?? 0); ?> · validated_phase0=<?php echo (int) ($runProposalCounts['validated_phase0'] ?? 0); ?></div>
        <div class="kpi">champion: <span class="mono"><?php echo htmlspecialchars((string) (($runChampionSummary['proposal']['proposal_id'] ?? '') ?: (($runChampionSummary['proposal_id'] ?? '') ?: '')), ENT_QUOTES, 'UTF-8'); ?></span></div>
        <div class="kpi">summary: <?php echo htmlspecialchars((string) ($runSummary['summary_text'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
    </div>

    <h2>Prompt Transparency</h2>
    <div class="panel">
        <div class="kpi">reference_models_count: <?php echo (int) ($referencesPayload['reference_models_count'] ?? count($referenceModels)); ?></div>
        <div class="kpi">reference_policy_version: <span class="mono"><?php echo htmlspecialchars((string) ($referencesPayload['reference_policy_version'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
        <table>
            <thead>
                <tr>
                    <th>Proposal</th>
                    <th>Score</th>
                    <th>Role</th>
                    <th>Reason</th>
                </tr>
            </thead>
            <tbody>
            <?php foreach ($referenceModels as $index => $reference): ?>
                <?php if (!is_array($reference)) { continue; } ?>
                <tr>
                    <td><?php echo htmlspecialchars((string) ($reference['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($reference['score'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($reference['role'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($reference['selection_reason'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>

    <h2>Model Shortlist</h2>
    <div class="panel">
        <?php if ($compareCandidateA !== '' && $compareCandidateB !== ''): ?>
            <div class="kpi"><a href="./monitor.php?compare_left=<?php echo rawurlencode($compareCandidateA); ?>&compare_right=<?php echo rawurlencode($compareCandidateB); ?>">Comparar top 2 models</a></div>
        <?php endif; ?>
        <table>
            <thead>
                <tr>
                    <th>Proposal</th>
                    <th>Score</th>
                    <th>Primary KPI</th>
                    <th>Status</th>
                    <th>Resume</th>
                    <th>Checkpoint epoch</th>
                    <th>Artifact</th>
                    <th>Availability</th>
                    <th>Download</th>
                    <th>Rationale</th>
                </tr>
            </thead>
            <tbody>
            <?php foreach ($modelShortlist as $model): ?>
                <?php if (!is_array($model)) { continue; } ?>
                <?php $artifact = (count($model['artifacts'] ?? []) > 0 && is_array($model['artifacts'][0] ?? null)) ? $model['artifacts'][0] : []; ?>
                <tr>
                    <td><?php echo htmlspecialchars((string) ($model['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($model['score'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($model['primary_kpi'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($model['status'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) (((($model['resume']['resumable'] ?? false)) ? 'yes' : 'no')), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($model['resume']['last_checkpoint_epoch'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td class="mono"><?php echo htmlspecialchars((string) ($model['trained_model_uri'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($artifact['availability_status'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td>
                        <?php if ((string) ($artifact['artifact_id'] ?? '') !== ''): ?>
                            <a href="./monitor.php?download_artifact_id=<?php echo rawurlencode((string) ($artifact['artifact_id'] ?? '')); ?>" target="_blank" rel="noreferrer">Descarregar</a>
                        <?php endif; ?>
                    </td>
                    <td><?php echo htmlspecialchars((string) ($model['rationale'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>

    <?php if (is_array($comparison)): ?>
        <?php
            $leftModel = is_array($comparison['left'] ?? null) ? $comparison['left'] : [];
            $rightModel = is_array($comparison['right'] ?? null) ? $comparison['right'] : [];
            $comparisonDelta = is_array($comparison['comparison'] ?? null) ? $comparison['comparison'] : [];
            $comparisonWinner = is_array($comparison['better_by'] ?? null) ? $comparison['better_by'] : [];
        ?>
        <h2>Model Comparison</h2>
        <div class="panel-grid">
            <div class="panel">
                <h3>Left</h3>
                <div class="kpi">proposal: <span class="mono"><?php echo htmlspecialchars((string) ($leftModel['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
                <div class="kpi">status: <?php echo htmlspecialchars((string) ($leftModel['status'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
                <div class="kpi">score: <?php echo htmlspecialchars((string) (($leftModel['selection_view']['score'] ?? '') ?: (($leftModel['champion']['score'] ?? '') ?: '')), ENT_QUOTES, 'UTF-8'); ?></div>
                <div class="kpi">artifact: <span class="mono"><?php echo htmlspecialchars((string) ($leftModel['trained_model_uri'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
            </div>
            <div class="panel">
                <h3>Right</h3>
                <div class="kpi">proposal: <span class="mono"><?php echo htmlspecialchars((string) ($rightModel['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
                <div class="kpi">status: <?php echo htmlspecialchars((string) ($rightModel['status'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
                <div class="kpi">score: <?php echo htmlspecialchars((string) (($rightModel['selection_view']['score'] ?? '') ?: (($rightModel['champion']['score'] ?? '') ?: '')), ENT_QUOTES, 'UTF-8'); ?></div>
                <div class="kpi">artifact: <span class="mono"><?php echo htmlspecialchars((string) ($rightModel['trained_model_uri'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
            </div>
        </div>
        <div class="panel">
            <div class="kpi">score_delta: <?php echo htmlspecialchars((string) ($comparisonDelta['score_delta'] ?? ''), ENT_QUOTES, 'UTF-8'); ?> · winner: <?php echo htmlspecialchars((string) ($comparisonWinner['score'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
            <div class="kpi">val_loss_delta: <?php echo htmlspecialchars((string) ($comparisonDelta['val_loss_delta'] ?? ''), ENT_QUOTES, 'UTF-8'); ?> · winner: <?php echo htmlspecialchars((string) ($comparisonWinner['val_loss_total'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
            <div class="kpi">training_time_delta: <?php echo htmlspecialchars((string) ($comparisonDelta['training_time_delta'] ?? ''), ENT_QUOTES, 'UTF-8'); ?> · winner: <?php echo htmlspecialchars((string) ($comparisonWinner['training_time_seconds'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
            <div class="kpi">train_loss_delta: <?php echo htmlspecialchars((string) ($comparisonDelta['train_loss_delta'] ?? ''), ENT_QUOTES, 'UTF-8'); ?> · winner: <?php echo htmlspecialchars((string) ($comparisonWinner['train_loss'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
        </div>
    <?php endif; ?>

    <h2>Champion Board</h2>
    <div class="panel-grid">
        <?php
            $runChampionEntry = is_array($championBoard['champion_run'] ?? null) ? $championBoard['champion_run'] : null;
            $runChampionProposal = is_array($runChampionEntry['proposal'] ?? null) ? $runChampionEntry['proposal'] : [];
            $runChampionDecision = is_array($runChampionEntry['decision'] ?? null) ? $runChampionEntry['decision'] : [];
            $runChampionMeta = is_array($runChampionProposal['llm_metadata'] ?? null) ? $runChampionProposal['llm_metadata'] : [];
            $runChampionPolicyProfile = (string) ($runChampionMeta['champion_policy_profile'] ?? ($championBoard['policy_profile'] ?? ''));
            $runProfileMismatch = $runChampionPolicyProfile !== ''
                && (string) ($championBoard['policy_profile'] ?? '') !== ''
                && $runChampionPolicyProfile !== (string) ($championBoard['policy_profile'] ?? '');
        ?>
        <div class="panel">
            <h3>Run Champion (latest run)</h3>
            <div class="kpi">run_id: <span class="mono"><?php echo htmlspecialchars((string) ($championBoard['latest_run_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
            <?php if (!empty($runChampionProposal)): ?>
                <div class="kpi">proposal: <span class="mono"><?php echo htmlspecialchars((string) ($runChampionProposal['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
                <div class="kpi">score: <strong><?php echo htmlspecialchars((string) ($runChampionDecision['score'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></strong></div>
                <div class="kpi">selection_reason: <?php echo htmlspecialchars((string) ($runChampionDecision['selection_reason'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
                <div class="kpi">status: <?php echo htmlspecialchars((string) ($runChampionProposal['status'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
                <div class="kpi">policy_version: <span class="mono"><?php echo htmlspecialchars((string) ($runChampionMeta['champion_policy_version'] ?? ($championBoard['policy_version'] ?? '')), ENT_QUOTES, 'UTF-8'); ?></span></div>
                <div class="kpi">policy_profile: <span class="mono"><?php echo htmlspecialchars($runChampionPolicyProfile, ENT_QUOTES, 'UTF-8'); ?></span></div>
                <?php if ($runProfileMismatch): ?>
                    <div class="kpi" style="color:#fbbf24;">⚠ profile mismatch (champion=<?php echo htmlspecialchars($runChampionPolicyProfile, ENT_QUOTES, 'UTF-8'); ?>, board=<?php echo htmlspecialchars((string) ($championBoard['policy_profile'] ?? ''), ENT_QUOTES, 'UTF-8'); ?>)</div>
                <?php endif; ?>
                <?php $runBreakdown = is_array($runChampionDecision['score_breakdown'] ?? null) ? $runChampionDecision['score_breakdown'] : []; ?>
                <?php $runNorm = is_array($runBreakdown['normalized'] ?? null) ? $runBreakdown['normalized'] : []; ?>
                <div class="kpi">breakdown: loss=<?php echo htmlspecialchars((string) ($runNorm['loss'] ?? ''), ENT_QUOTES, 'UTF-8'); ?> · time=<?php echo htmlspecialchars((string) ($runNorm['time'] ?? ''), ENT_QUOTES, 'UTF-8'); ?> · stability=<?php echo htmlspecialchars((string) ($runNorm['stability'] ?? ''), ENT_QUOTES, 'UTF-8'); ?> · quality=<?php echo htmlspecialchars((string) ($runNorm['quality'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
            <?php else: ?>
                <div class="kpi">No champion for latest run yet.</div>
            <?php endif; ?>
        </div>

        <?php
            $globalChampionEntry = is_array($championBoard['champion_global'] ?? null) ? $championBoard['champion_global'] : null;
            $globalChampionProposal = is_array($globalChampionEntry['proposal'] ?? null) ? $globalChampionEntry['proposal'] : [];
            $globalChampionDecision = is_array($globalChampionEntry['decision'] ?? null) ? $globalChampionEntry['decision'] : [];
            $globalChampionMeta = is_array($globalChampionProposal['llm_metadata'] ?? null) ? $globalChampionProposal['llm_metadata'] : [];
            $globalChampionPolicyProfile = (string) ($globalChampionMeta['champion_policy_profile'] ?? ($championBoard['policy_profile'] ?? ''));
            $globalProfileMismatch = $globalChampionPolicyProfile !== ''
                && (string) ($championBoard['policy_profile'] ?? '') !== ''
                && $globalChampionPolicyProfile !== (string) ($championBoard['policy_profile'] ?? '');
        ?>
        <div class="panel">
            <h3>Global Champion</h3>
            <?php if (!empty($globalChampionProposal)): ?>
                <div class="kpi">proposal: <span class="mono"><?php echo htmlspecialchars((string) ($globalChampionProposal['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
                <div class="kpi">score: <strong><?php echo htmlspecialchars((string) ($globalChampionDecision['score'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></strong></div>
                <div class="kpi">selection_reason: <?php echo htmlspecialchars((string) ($globalChampionDecision['selection_reason'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
                <div class="kpi">status: <?php echo htmlspecialchars((string) ($globalChampionProposal['status'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
                <div class="kpi">policy_version: <span class="mono"><?php echo htmlspecialchars((string) ($globalChampionMeta['champion_policy_version'] ?? ($championBoard['policy_version'] ?? '')), ENT_QUOTES, 'UTF-8'); ?></span></div>
                <div class="kpi">policy_profile: <span class="mono"><?php echo htmlspecialchars($globalChampionPolicyProfile, ENT_QUOTES, 'UTF-8'); ?></span></div>
                <?php if ($globalProfileMismatch): ?>
                    <div class="kpi" style="color:#fbbf24;">⚠ profile mismatch (champion=<?php echo htmlspecialchars($globalChampionPolicyProfile, ENT_QUOTES, 'UTF-8'); ?>, board=<?php echo htmlspecialchars((string) ($championBoard['policy_profile'] ?? ''), ENT_QUOTES, 'UTF-8'); ?>)</div>
                <?php endif; ?>
                <?php $globalBreakdown = is_array($globalChampionDecision['score_breakdown'] ?? null) ? $globalChampionDecision['score_breakdown'] : []; ?>
                <?php $globalNorm = is_array($globalBreakdown['normalized'] ?? null) ? $globalBreakdown['normalized'] : []; ?>
                <div class="kpi">breakdown: loss=<?php echo htmlspecialchars((string) ($globalNorm['loss'] ?? ''), ENT_QUOTES, 'UTF-8'); ?> · time=<?php echo htmlspecialchars((string) ($globalNorm['time'] ?? ''), ENT_QUOTES, 'UTF-8'); ?> · stability=<?php echo htmlspecialchars((string) ($globalNorm['stability'] ?? ''), ENT_QUOTES, 'UTF-8'); ?> · quality=<?php echo htmlspecialchars((string) ($globalNorm['quality'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></div>
            <?php else: ?>
                <div class="kpi">No global champion yet.</div>
            <?php endif; ?>
        </div>
    </div>

    <div class="panel-grid">
        <div class="panel">
            <h3>Top-N Run Candidates</h3>
            <table>
                <thead>
                    <tr>
                        <th>Proposal</th>
                        <th>Status</th>
                        <th>Score</th>
                        <th>Delta</th>
                        <th>Factors</th>
                        <th>Reason</th>
                    </tr>
                </thead>
                <tbody>
                <?php foreach ((array) ($championBoard['run_top'] ?? []) as $entry): ?>
                    <?php
                        $proposal = is_array($entry['proposal'] ?? null) ? $entry['proposal'] : [];
                        $decision = is_array($entry['decision'] ?? null) ? $entry['decision'] : [];
                        $factors = is_array($entry['primary_factors'] ?? null) ? $entry['primary_factors'] : [];
                    ?>
                    <tr>
                        <td><?php echo htmlspecialchars((string) ($proposal['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                        <td><?php echo htmlspecialchars((string) ($proposal['status'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                        <td><?php echo htmlspecialchars((string) ($decision['score'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                        <td><?php echo htmlspecialchars((string) ($entry['delta_from_previous'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                        <td><?php echo htmlspecialchars(implode(', ', array_map(static fn(array $item): string => (string) ($item['name'] ?? ''), $factors)), ENT_QUOTES, 'UTF-8'); ?></td>
                        <td><?php echo htmlspecialchars((string) ($decision['selection_reason'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    </tr>
                <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <div class="panel">
            <h3>Top-N Global Candidates</h3>
            <table>
                <thead>
                    <tr>
                        <th>Proposal</th>
                        <th>Status</th>
                        <th>Score</th>
                        <th>Delta</th>
                        <th>Factors</th>
                        <th>Reason</th>
                    </tr>
                </thead>
                <tbody>
                <?php foreach ((array) ($championBoard['global_top'] ?? []) as $entry): ?>
                    <?php
                        $proposal = is_array($entry['proposal'] ?? null) ? $entry['proposal'] : [];
                        $decision = is_array($entry['decision'] ?? null) ? $entry['decision'] : [];
                        $factors = is_array($entry['primary_factors'] ?? null) ? $entry['primary_factors'] : [];
                    ?>
                    <tr>
                        <td><?php echo htmlspecialchars((string) ($proposal['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                        <td><?php echo htmlspecialchars((string) ($proposal['status'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                        <td><?php echo htmlspecialchars((string) ($decision['score'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                        <td><?php echo htmlspecialchars((string) ($entry['delta_from_previous'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                        <td><?php echo htmlspecialchars(implode(', ', array_map(static fn(array $item): string => (string) ($item['name'] ?? ''), $factors)), ENT_QUOTES, 'UTF-8'); ?></td>
                        <td><?php echo htmlspecialchars((string) ($decision['selection_reason'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    </tr>
                <?php endforeach; ?>
                </tbody>
            </table>
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>Run ID</th>
                <th>Status</th>
                <th>Generation</th>
                <th>Code Version</th>
                <th>Updated</th>
                <th>Summary</th>
                <th>Timeline</th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($runs as $run): ?>
                <?php
                    $status = (string) ($run['status'] ?? '');
                    $statusClass = 'status-' . htmlspecialchars($status, ENT_QUOTES, 'UTF-8');
                    $runId = htmlspecialchars((string) ($run['run_id'] ?? ''), ENT_QUOTES, 'UTF-8');
                    $summaryPath = './monitor.php?summary_run_id=' . rawurlencode((string) ($run['run_id'] ?? ''));
                    $timelinePath = './monitor.php?timeline_run_id=' . rawurlencode((string) ($run['run_id'] ?? ''));
                ?>
                <tr>
                    <td><?php echo $runId; ?></td>
                    <td class="<?php echo $statusClass; ?>"><?php echo htmlspecialchars($status, ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo (int) ($run['generation'] ?? 0); ?></td>
                    <td><?php echo htmlspecialchars((string) ($run['code_version'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($run['updated_at'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><a href="<?php echo $summaryPath; ?>" target="_blank" rel="noreferrer">Veure summary</a></td>
                    <td><a href="<?php echo $timelinePath; ?>" target="_blank" rel="noreferrer">Veure timeline</a></td>
                </tr>
            <?php endforeach; ?>
        </tbody>
    </table>
    <h2>Model Proposals</h2>
    <table>
        <thead>
            <tr>
                <th>Proposal ID</th>
                <th>Status</th>
                <th>Source Run</th>
                <th>Base Model</th>
                <th>Updated</th>
                <th>Score</th>
                <th>KPI</th>
                <th>Resume</th>
                <th>Checkpoint epoch</th>
                <th>Artifact</th>
                <th>Availability</th>
                <th>Download</th>
                <th>LLM prompt/response</th>
                <th>Detail</th>
                <th>Canviar status</th>
                <th>Acció</th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($proposals as $proposal): ?>
                <?php
                    $proposalStatus = (string) ($proposal['status'] ?? '');
                    $proposalStatusClass = 'status-' . htmlspecialchars($proposalStatus, ENT_QUOTES, 'UTF-8');
                    $proposalId = (string) ($proposal['proposal_id'] ?? '');
                    $proposalIdEscaped = htmlspecialchars($proposalId, ENT_QUOTES, 'UTF-8');
                    $proposalDetailPath = './monitor.php?proposal_id=' . rawurlencode($proposalId);
                    $proposalChampion = is_array($proposal['champion'] ?? null) ? $proposal['champion'] : [];
                    $proposalKpis = is_array($proposal['training_kpis'] ?? null) ? $proposal['training_kpis'] : [];
                    $primaryArtifact = is_array($proposal['primary_artifact'] ?? null) ? $proposal['primary_artifact'] : [];
                    $resumeState = is_array($proposal['resume'] ?? null) ? $proposal['resume'] : [];
                    $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
                    $promptAudit = is_array($llmMetadata['prompt_audit'] ?? null) ? $llmMetadata['prompt_audit'] : [];
                    $promptText = (string) ($promptAudit['prompt_text'] ?? '');
                    $promptChars = (int) ($promptAudit['prompt_chars'] ?? strlen($promptText));
                    $promptHash = (string) ($promptAudit['prompt_sha256'] ?? '');
                    $responseText = llmResponseTextFromMetadata($llmMetadata);
                    $responseChars = (int) ($llmMetadata['response_chars'] ?? strlen($responseText));
                ?>
                <tr>
                    <td><?php echo $proposalIdEscaped; ?></td>
                    <td class="<?php echo $proposalStatusClass; ?>"><?php echo htmlspecialchars($proposalStatus, ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposal['source_run_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposal['base_model_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposal['updated_at'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposalChampion['score'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposalKpis['val_loss_total'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ((($resumeState['resumable'] ?? false) ? 'yes' : 'no')), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($resumeState['last_checkpoint_epoch'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($primaryArtifact['artifact_type'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($primaryArtifact['availability_status'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td>
                        <?php if ((string) ($primaryArtifact['artifact_id'] ?? '') !== ''): ?>
                            <a href="./monitor.php?download_artifact_id=<?php echo rawurlencode((string) ($primaryArtifact['artifact_id'] ?? '')); ?>" target="_blank" rel="noreferrer">Descarregar</a>
                        <?php endif; ?>
                    </td>
                    <td>
                        <?php if ($promptText !== '' || $responseText !== ''): ?>
                            <div class="kpi">provider: <span class="mono"><?php echo htmlspecialchars((string) ($llmMetadata['provider'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
                            <div class="kpi">gen/candidate: <span class="mono"><?php echo htmlspecialchars((string) ($llmMetadata['from_generation'] ?? ''), ENT_QUOTES, 'UTF-8'); ?>/<?php echo htmlspecialchars((string) ($llmMetadata['candidate_index'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
                            <div class="kpi">prompt chars: <span class="mono"><?php echo htmlspecialchars((string) $promptChars, ENT_QUOTES, 'UTF-8'); ?></span></div>
                            <div class="kpi">response chars: <span class="mono"><?php echo htmlspecialchars((string) $responseChars, ENT_QUOTES, 'UTF-8'); ?></span></div>
                            <?php if ($promptHash !== ''): ?><div class="kpi">prompt sha256: <span class="mono"><?php echo htmlspecialchars($promptHash, ENT_QUOTES, 'UTF-8'); ?></span></div><?php endif; ?>
                            <details>
                                <summary>Veure prompt + resposta</summary>
                                <?php if ($promptText !== ''): ?>
                                <div class="kpi" style="margin-top:6px;">Prompt</div>
                                <pre style="font-size:11px; margin:0; background:#1e293b; padding:4px; overflow:auto; max-width:520px; max-height:220px;"><?php echo htmlspecialchars($promptText, ENT_QUOTES, 'UTF-8'); ?></pre>
                                <?php endif; ?>
                                <?php if ($responseText !== ''): ?>
                                <div class="kpi" style="margin-top:6px;">Resposta</div>
                                <pre style="font-size:11px; margin:0; background:#1e293b; padding:4px; overflow:auto; max-width:520px; max-height:220px;"><?php echo htmlspecialchars($responseText, ENT_QUOTES, 'UTF-8'); ?></pre>
                                <?php endif; ?>
                            </details>
                        <?php else: ?>
                            <span class="kpi">sense traça LLM</span>
                        <?php endif; ?>
                    </td>
                    <td><a href="<?php echo $proposalDetailPath; ?>" target="_blank" rel="noreferrer">Veure proposta</a></td>
                    <td>
                        <form method="post" action="./monitor.php">
                            <input type="hidden" name="action" value="proposal_status">
                            <input type="hidden" name="proposal_id" value="<?php echo $proposalIdEscaped; ?>">
                            <select name="status">
                                <option value="draft">draft</option>
                                <option value="queued_phase0">queued_phase0</option>
                                <option value="validated_phase0">validated_phase0</option>
                                <option value="accepted">accepted</option>
                                <option value="rejected">rejected</option>
                            </select>
                            <button type="submit">Aplicar</button>
                        </form>
                    </td>
                    <td>
                        <form method="post" action="./monitor.php">
                            <input type="hidden" name="action" value="proposal_enqueue_phase0">
                            <input type="hidden" name="proposal_id" value="<?php echo $proposalIdEscaped; ?>">
                            <button type="submit">Enviar a phase0</button>
                        </form>
                    </td>
                </tr>
            <?php endforeach; ?>
        </tbody>
    </table>
    
    <h2>Events Recents</h2>
    <table>
        <thead>
            <tr>
                <th>Timestamp</th>
                <th>Run ID</th>
                <th>Tipus</th>
                <th>Nivell</th>
                <th>Etiqueta</th>
                <th>Detalls</th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($recentEvents as $event): ?>
                <tr>
                    <td><?php echo htmlspecialchars((string) ($event['timestamp'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($event['run_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($event['event_type'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($event['level'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($event['label'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td>
                        <details>
                            <summary>Veure JSON</summary>
                            <pre style="font-size: 11px; margin: 0; background: #1e293b; padding: 4px; overflow-x: auto;">
<?php echo htmlspecialchars(json_encode($event['details'] ?? [], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT), ENT_QUOTES, 'UTF-8'); ?>
                            </pre>
                        </details>
                    </td>
                </tr>
            <?php endforeach; ?>
        </tbody>
    </table>

    <h2>Mètriques Recents</h2>
    <table>
        <thead>
            <tr>
                <th>Timestamp</th>
                <th>Run ID</th>
                <th>Model ID</th>
                <th>Generació</th>
                <th>Mètriques</th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($recentMetrics as $metric): ?>
                <tr>
                    <td><?php echo htmlspecialchars((string) ($metric['timestamp'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($metric['run_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($metric['model_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo (int) ($metric['generation'] ?? 0); ?></td>
                    <td>
                        <details>
                            <summary>Veure JSON</summary>
                            <pre style="font-size: 11px; margin: 0; background: #1e293b; padding: 4px; overflow-x: auto;">
<?php echo htmlspecialchars(json_encode($metric['metrics'] ?? [], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT), ENT_QUOTES, 'UTF-8'); ?>
                            </pre>
                        </details>
                    </td>
                </tr>
            <?php endforeach; ?>
        </tbody>
    </table>
    <script>
        (function () {
            const form = document.getElementById('execution-create-form');
            if (!form) return;

            const requestTypeHelp = document.getElementById('request_type_help');
            const profileHelp = document.getElementById('profile_help');
            const totalModels = document.getElementById('plan-total-models');
            const profileLine = document.getElementById('plan-profile-line');
            const typeLine = document.getElementById('plan-type-line');
            const optionsLine = document.getElementById('plan-options-line');
            const limitsLine = document.getElementById('plan-limits-line');
            const durationLine = document.getElementById('plan-duration-line');

            const requestTypeDescriptions = {
                smoke_run: 'Prova ràpida end-to-end.',
                micro_training: 'Entrenament curt real.',
                integration_matrix: 'Múltiples runs per validar consistència.',
                resume_training: 'Reprèn entrenaments interromputs.',
                cleanup: 'Neteja estat inconsistent.'
            };
            const profileDescriptions = {
                small_test: 'Execució ràpida per validar pipeline i control operatiu.',
                default: 'Configuració equilibrada entre temps i qualitat.',
                real_large: 'Dataset gran i execució costosa; orientat a qualitat real.'
            };
            const perModelMinutes = {
                small_test: 4,
                default: 8,
                real_large: 18
            };

            function asPositiveInt(value, fallback) {
                const parsed = parseInt(value, 10);
                return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
            }

            function updatePlanSummary() {
                const requestType = form.elements['request_type'].value;
                const profile = form.elements['profile'].value;
                const generations = asPositiveInt(form.elements['generations'].value, 1);
                const modelsPerGeneration = asPositiveInt(form.elements['models_per_generation'].value, 1);
                const total = generations * modelsPerGeneration;
                const estimatedMinutes = Math.max(2, total * (perModelMinutes[profile] || 4));
                const resumeEnabled = form.elements['resume_enabled'].value === '1' ? 'Resume activat' : 'Resume desactivat';
                const championScope = 'champion ' + form.elements['champion_scope'].value;
                const maxEpochs = asPositiveInt(form.elements['max_epochs'].value, 0);
                const maxTrainingSeconds = asPositiveInt(form.elements['max_training_seconds'].value, 0);
                const epochsLabel = maxEpochs > 0 ? ('màxim ' + maxEpochs + ' èpoques') : 'èpoques del model';
                const timeLabel = maxTrainingSeconds > 0 ? ('màxim ' + maxTrainingSeconds + 's') : 'temps lliure';

                requestTypeHelp.textContent = requestTypeDescriptions[requestType] || 'Tipus d’execució personalitzat.';
                profileHelp.textContent = profileDescriptions[profile] || '';
                totalModels.textContent = generations + ' generacions × ' + modelsPerGeneration + ' models = ' + total + ' models totals';
                profileLine.textContent = 'Perfil ' + profile + ' · ' + (profileDescriptions[profile] || '');
                typeLine.textContent = 'Tipus ' + requestType + ' · ' + (requestTypeDescriptions[requestType] || '');
                optionsLine.textContent = resumeEnabled + ' · ' + championScope;
                limitsLine.textContent = 'Límits: ' + epochsLabel + ' · ' + timeLabel;
                durationLine.textContent = 'Estimació de durada: ' + estimatedMinutes + ' min';
            }

            form.querySelectorAll('select, input').forEach((element) => {
                element.addEventListener('change', updatePlanSummary);
                element.addEventListener('input', updatePlanSummary);
            });

            updatePlanSummary();
        })();
    </script>
</body>
</html>
