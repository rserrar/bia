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
    echo '<h1>V2 Monitor</h1><p>Introdueix el token per iniciar sessió.</p>';
    echo '<form method="get" action="./monitor.php">';
    echo '<input type="password" name="token" placeholder="Token" required>';
    echo '<button type="submit">Entrar</button>';
    echo '</form></body></html>';
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
        $summary = $service->getSummary($summaryRunId);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($summary, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit;
    }
    $proposalId = is_string($_GET['proposal_id'] ?? null) ? (string) $_GET['proposal_id'] : '';
    if ($proposalId !== '') {
        $proposal = $service->getModelProposal($proposalId);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode($proposal, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
        exit;
    }
    $runs = $service->listRuns(100);
    $proposals = $service->listModelProposals(100);
    $recentEvents = $service->listEvents(50);
    $recentMetrics = $service->listMetrics(50);
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
    <table>
        <thead>
            <tr>
                <th>Run ID</th>
                <th>Status</th>
                <th>Generation</th>
                <th>Code Version</th>
                <th>Updated</th>
                <th>Summary</th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($runs as $run): ?>
                <?php
                    $status = (string) ($run['status'] ?? '');
                    $statusClass = 'status-' . htmlspecialchars($status, ENT_QUOTES, 'UTF-8');
                    $runId = htmlspecialchars((string) ($run['run_id'] ?? ''), ENT_QUOTES, 'UTF-8');
                    $summaryPath = './monitor.php?summary_run_id=' . rawurlencode((string) ($run['run_id'] ?? ''));
                ?>
                <tr>
                    <td><?php echo $runId; ?></td>
                    <td class="<?php echo $statusClass; ?>"><?php echo htmlspecialchars($status, ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo (int) ($run['generation'] ?? 0); ?></td>
                    <td><?php echo htmlspecialchars((string) ($run['code_version'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($run['updated_at'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><a href="<?php echo $summaryPath; ?>" target="_blank" rel="noreferrer">Veure summary</a></td>
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
                ?>
                <tr>
                    <td><?php echo $proposalIdEscaped; ?></td>
                    <td class="<?php echo $proposalStatusClass; ?>"><?php echo htmlspecialchars($proposalStatus, ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposal['source_run_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposal['base_model_id'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
                    <td><?php echo htmlspecialchars((string) ($proposal['updated_at'] ?? ''), ENT_QUOTES, 'UTF-8'); ?></td>
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
