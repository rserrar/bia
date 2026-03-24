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
        if ($confirm === 'RESET') {
            $_SESSION['reset_result'] = $service->resetAllData();
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
    $compareLeft = is_string($_GET['compare_left'] ?? null) ? (string) $_GET['compare_left'] : '';
    $compareRight = is_string($_GET['compare_right'] ?? null) ? (string) $_GET['compare_right'] : '';
    if ($compareLeft !== '' && $compareRight !== '') {
        $comparison = monitorApiRequest('/models/compare?left=' . rawurlencode($compareLeft) . '&right=' . rawurlencode($compareRight));
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($comparison, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit;
    }
    $proposalId = is_string($_GET['proposal_id'] ?? null) ? (string) $_GET['proposal_id'] : '';
    if ($proposalId !== '') {
        $proposal = monitorApiRequest('/models/' . rawurlencode($proposalId) . '/detail-view');
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($proposal, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit;
    }
    $runsPayload = monitorApiRequest('/runs?limit=100');
    $proposalsPayload = monitorApiRequest('/proposals?limit=100');
    $recentEventsPayload = monitorApiRequest('/events?limit=15');
    $recentMetricsPayload = monitorApiRequest('/metrics?limit=50');
    $globalChampionPayload = monitorApiRequest('/champion/global?top_n=5');
    $shortlistPayload = monitorApiRequest('/models/shortlist?limit=5');

    $runs = is_array($runsPayload['runs'] ?? null) ? $runsPayload['runs'] : [];
    $proposals = is_array($proposalsPayload['proposals'] ?? null) ? $proposalsPayload['proposals'] : [];
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
    <meta http-equiv="refresh" content="15">
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
        select, button { background: #0b1220; color: #e2e8f0; border: 1px solid #334155; padding: 4px 6px; border-radius: 4px; }
    </style>
</head>
<body>
    <h1>V2 Monitor</h1>
    <?php 
        $resetResult = is_array($_SESSION['reset_result'] ?? null) ? $_SESSION['reset_result'] : null; unset($_SESSION['reset_result']); 
        $evalResult = is_array($_SESSION['eval_result'] ?? null) ? $_SESSION['eval_result'] : null; unset($_SESSION['eval_result']); 
    ?>
    <div class="meta">Actualització automàtica cada 15s · Runs: <?php echo count($runs); ?> · <a href="./monitor.php?logout=1">Sortir</a></div>
    <div class="meta">Selection policy: <span class="mono"><?php echo htmlspecialchars((string) ($championBoard['policy_version'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span> · profile: <span class="mono"><?php echo htmlspecialchars((string) ($championBoard['policy_profile'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></span></div>
    <div class="toolbar">
        <form method="post" action="./monitor.php">
            <input type="hidden" name="action" value="evaluate_kpis">
            <input type="number" name="threshold" value="0.5" step="0.01" style="width: 70px;">
            <button type="submit">Avaluar KPIs (promoure models)</button>
        </form>
        <form method="post" action="./monitor.php">
            <input type="hidden" name="action" value="reset_all_data">
            <input type="hidden" name="confirm" value="RESET">
            <button type="submit" class="danger" onclick="return confirm('Vols esborrar totes les dades de prova?');">Reset dades prova</button>
        </form>
        <?php if ($resetResult !== null): ?>
            <span class="notice">Reset fet · Runs: <?php echo (int) ($resetResult['deleted']['runs'] ?? 0); ?> · Events: <?php echo (int) ($resetResult['deleted']['events'] ?? 0); ?> · Metrics: <?php echo (int) ($resetResult['deleted']['metrics'] ?? 0); ?> · Artifacts: <?php echo (int) ($resetResult['deleted']['artifacts'] ?? 0); ?> · Proposals: <?php echo (int) ($resetResult['deleted']['model_proposals'] ?? 0); ?></span>
        <?php endif; ?>
        <?php if ($evalResult !== null): ?>
            <span class="notice">Models avaluats (KPIs): <?php echo (int) ($evalResult['evaluated_count'] ?? 0); ?></span>
        <?php endif; ?>
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
            <div class="kpi"><a href="./monitor.php?compare_left=<?php echo rawurlencode($compareCandidateA); ?>&compare_right=<?php echo rawurlencode($compareCandidateB); ?>" target="_blank" rel="noreferrer">Comparar top 2 models</a></div>
        <?php endif; ?>
        <table>
            <thead>
                <tr>
                    <th>Proposal</th>
                    <th>Score</th>
                    <th>Primary KPI</th>
                    <th>Status</th>
                    <th>Artifact</th>
                    <th>Rationale</th>
                </tr>
            </thead>
            <tbody>
            <?php foreach ($modelShortlist as $model): ?>
                <?php if (!is_array($model)) { continue; } ?>
                <tr>
                    <td><?php echo htmlspecialchars((string) ($model['proposal_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($model['score'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($model['primary_kpi'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($model['status'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td class="mono"><?php echo htmlspecialchars((string) ($model['trained_model_uri'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($model['rationale'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>

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
                ?>
                <tr>
                    <td><?php echo $proposalIdEscaped; ?></td>
                    <td class="<?php echo $proposalStatusClass; ?>"><?php echo htmlspecialchars($proposalStatus, ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposal['source_run_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposal['base_model_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposal['updated_at'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposalChampion['score'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposalKpis['val_loss_total'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
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
</body>
</html>
