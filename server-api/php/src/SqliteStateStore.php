<?php

declare(strict_types=1);

namespace V2ServerApi;

use PDO;
use RuntimeException;

final class SqliteStateStore
{
    private PDO $pdo;

    public function __construct(string $databasePath)
    {
        if (!extension_loaded('pdo_sqlite')) {
            throw new RuntimeException('pdo_sqlite extension is required for sqlite storage backend');
        }
        $dir = dirname($databasePath);
        if (!is_dir($dir)) {
            mkdir($dir, 0777, true);
        }
        $this->pdo = new PDO('sqlite:' . $databasePath);
        $this->pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $this->initializeSchema();
    }

    public function readAll(): array
    {
        $runs = [];
        $runRows = $this->pdo->query(
            'SELECT run_id, status, created_at, updated_at, code_version, generation, heartbeat_at, metadata_json FROM runs'
        );
        if ($runRows !== false) {
            foreach ($runRows as $row) {
                $runs[(string) $row['run_id']] = [
                    'run_id' => (string) $row['run_id'],
                    'status' => (string) $row['status'],
                    'created_at' => (string) $row['created_at'],
                    'updated_at' => (string) $row['updated_at'],
                    'code_version' => (string) $row['code_version'],
                    'generation' => (int) $row['generation'],
                    'heartbeat_at' => $row['heartbeat_at'] === null ? null : (string) $row['heartbeat_at'],
                    'metadata' => $this->decodeArray((string) $row['metadata_json']),
                ];
            }
        }

        $events = [];
        $eventRows = $this->pdo->query(
            'SELECT run_id, event_type, label, level, timestamp, details_json FROM events ORDER BY id ASC'
        );
        if ($eventRows !== false) {
            foreach ($eventRows as $row) {
                $events[] = [
                    'run_id' => (string) $row['run_id'],
                    'event_type' => (string) $row['event_type'],
                    'label' => (string) $row['label'],
                    'level' => (string) $row['level'],
                    'timestamp' => (string) $row['timestamp'],
                    'details' => $this->decodeArray((string) $row['details_json']),
                ];
            }
        }

        $metrics = [];
        $metricRows = $this->pdo->query(
            'SELECT run_id, model_id, generation, metrics_json, timestamp FROM metrics ORDER BY id ASC'
        );
        if ($metricRows !== false) {
            foreach ($metricRows as $row) {
                $metrics[] = [
                    'run_id' => (string) $row['run_id'],
                    'model_id' => (string) $row['model_id'],
                    'generation' => (int) $row['generation'],
                    'metrics' => $this->decodeArray((string) $row['metrics_json']),
                    'timestamp' => (string) $row['timestamp'],
                ];
            }
        }

        $artifacts = [];
        $artifactRows = $this->pdo->query(
            'SELECT run_id, artifact_type, uri, checksum, storage, metadata_json, timestamp FROM artifacts ORDER BY id ASC'
        );
        if ($artifactRows !== false) {
            foreach ($artifactRows as $row) {
                $artifacts[] = [
                    'run_id' => (string) $row['run_id'],
                    'artifact_type' => (string) $row['artifact_type'],
                    'uri' => (string) $row['uri'],
                    'checksum' => $row['checksum'] === null ? null : (string) $row['checksum'],
                    'storage' => (string) $row['storage'],
                    'metadata' => $this->decodeArray((string) $row['metadata_json']),
                    'timestamp' => (string) $row['timestamp'],
                ];
            }
        }

        $modelProposals = [];
        $proposalRows = $this->pdo->query(
            'SELECT proposal_id, status, source_run_id, base_model_id, proposal_json, llm_metadata_json, created_at, updated_at
             FROM model_proposals ORDER BY id DESC'
        );
        if ($proposalRows !== false) {
            foreach ($proposalRows as $row) {
                $modelProposals[] = [
                    'proposal_id' => (string) $row['proposal_id'],
                    'status' => (string) $row['status'],
                    'source_run_id' => (string) $row['source_run_id'],
                    'base_model_id' => (string) $row['base_model_id'],
                    'proposal' => $this->decodeArray((string) $row['proposal_json']),
                    'llm_metadata' => $this->decodeArray((string) $row['llm_metadata_json']),
                    'created_at' => (string) $row['created_at'],
                    'updated_at' => (string) $row['updated_at'],
                ];
            }
        }

        $executionRequests = [];
        $requestRows = $this->pdo->query(
            'SELECT request_id, type, status, config_json, created_at, updated_at, claimed_by_worker, claimed_at, heartbeat_at, attempts, result_summary_json, result_artifacts_json, error_summary
             FROM execution_requests ORDER BY id DESC'
        );
        if ($requestRows !== false) {
            foreach ($requestRows as $row) {
                $executionRequests[] = [
                    'request_id' => (string) $row['request_id'],
                    'type' => (string) $row['type'],
                    'status' => (string) $row['status'],
                    'config' => $this->decodeArray((string) $row['config_json']),
                    'created_at' => (string) $row['created_at'],
                    'updated_at' => (string) $row['updated_at'],
                    'claimed_by_worker' => $row['claimed_by_worker'] === null ? null : (string) $row['claimed_by_worker'],
                    'claimed_at' => $row['claimed_at'] === null ? null : (string) $row['claimed_at'],
                    'heartbeat_at' => $row['heartbeat_at'] === null ? null : (string) $row['heartbeat_at'],
                    'attempts' => (int) $row['attempts'],
                    'result_summary' => $this->decodeArray((string) $row['result_summary_json']),
                    'result_artifacts' => $this->decodeArray((string) $row['result_artifacts_json']),
                    'error_summary' => $row['error_summary'] === null ? null : (string) $row['error_summary'],
                ];
            }
        }

        return [
            'runs' => $runs,
            'events' => $events,
            'metrics' => $metrics,
            'artifacts' => $artifacts,
            'model_proposals' => $modelProposals,
            'execution_requests' => $executionRequests,
        ];
    }

    public function upsertRun(array $run): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO runs (run_id, status, created_at, updated_at, code_version, generation, heartbeat_at, metadata_json)
             VALUES (:run_id, :status, :created_at, :updated_at, :code_version, :generation, :heartbeat_at, :metadata_json)
             ON CONFLICT(run_id) DO UPDATE SET
               status = excluded.status,
               created_at = excluded.created_at,
               updated_at = excluded.updated_at,
               code_version = excluded.code_version,
               generation = excluded.generation,
               heartbeat_at = excluded.heartbeat_at,
               metadata_json = excluded.metadata_json'
        );
        $stmt->execute([
            ':run_id' => (string) ($run['run_id'] ?? ''),
            ':status' => (string) ($run['status'] ?? ''),
            ':created_at' => (string) ($run['created_at'] ?? ''),
            ':updated_at' => (string) ($run['updated_at'] ?? ''),
            ':code_version' => (string) ($run['code_version'] ?? ''),
            ':generation' => (int) ($run['generation'] ?? 0),
            ':heartbeat_at' => isset($run['heartbeat_at']) && $run['heartbeat_at'] !== '' ? (string) $run['heartbeat_at'] : null,
            ':metadata_json' => (string) json_encode($run['metadata'] ?? [], JSON_UNESCAPED_UNICODE),
        ]);
    }

    public function appendEvent(array $event): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO events (run_id, event_type, label, level, timestamp, details_json)
             VALUES (:run_id, :event_type, :label, :level, :timestamp, :details_json)'
        );
        $stmt->execute([
            ':run_id' => (string) ($event['run_id'] ?? ''),
            ':event_type' => (string) ($event['event_type'] ?? ''),
            ':label' => (string) ($event['label'] ?? ''),
            ':level' => (string) ($event['level'] ?? 'info'),
            ':timestamp' => (string) ($event['timestamp'] ?? ''),
            ':details_json' => (string) json_encode($event['details'] ?? [], JSON_UNESCAPED_UNICODE),
        ]);
    }

    public function appendMetric(array $metric): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO metrics (run_id, model_id, generation, metrics_json, timestamp)
             VALUES (:run_id, :model_id, :generation, :metrics_json, :timestamp)'
        );
        $stmt->execute([
            ':run_id' => (string) ($metric['run_id'] ?? ''),
            ':model_id' => (string) ($metric['model_id'] ?? ''),
            ':generation' => (int) ($metric['generation'] ?? 0),
            ':metrics_json' => (string) json_encode($metric['metrics'] ?? [], JSON_UNESCAPED_UNICODE),
            ':timestamp' => (string) ($metric['timestamp'] ?? ''),
        ]);
    }

    public function appendArtifact(array $artifact): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO artifacts (run_id, artifact_type, uri, checksum, storage, metadata_json, timestamp)
             VALUES (:run_id, :artifact_type, :uri, :checksum, :storage, :metadata_json, :timestamp)'
        );
        $stmt->execute([
            ':run_id' => (string) ($artifact['run_id'] ?? ''),
            ':artifact_type' => (string) ($artifact['artifact_type'] ?? ''),
            ':uri' => (string) ($artifact['uri'] ?? ''),
            ':checksum' => isset($artifact['checksum']) && $artifact['checksum'] !== '' ? (string) $artifact['checksum'] : null,
            ':storage' => (string) ($artifact['storage'] ?? 'drive'),
            ':metadata_json' => (string) json_encode($artifact['metadata'] ?? [], JSON_UNESCAPED_UNICODE),
            ':timestamp' => (string) ($artifact['timestamp'] ?? ''),
        ]);
    }

    public function appendModelProposal(array $proposal): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO model_proposals (
                proposal_id, status, source_run_id, base_model_id, proposal_json, llm_metadata_json, created_at, updated_at
             ) VALUES (
                :proposal_id, :status, :source_run_id, :base_model_id, :proposal_json, :llm_metadata_json, :created_at, :updated_at
             )'
        );
        $stmt->execute([
            ':proposal_id' => (string) ($proposal['proposal_id'] ?? ''),
            ':status' => (string) ($proposal['status'] ?? 'draft'),
            ':source_run_id' => (string) ($proposal['source_run_id'] ?? ''),
            ':base_model_id' => (string) ($proposal['base_model_id'] ?? ''),
            ':proposal_json' => (string) json_encode($proposal['proposal'] ?? [], JSON_UNESCAPED_UNICODE),
            ':llm_metadata_json' => (string) json_encode($proposal['llm_metadata'] ?? [], JSON_UNESCAPED_UNICODE),
            ':created_at' => (string) ($proposal['created_at'] ?? ''),
            ':updated_at' => (string) ($proposal['updated_at'] ?? ''),
        ]);
    }

    public function replaceModelProposal(string $proposalId, array $proposal): void
    {
        $stmt = $this->pdo->prepare(
            'UPDATE model_proposals
             SET status = :status,
                 source_run_id = :source_run_id,
                 base_model_id = :base_model_id,
                 proposal_json = :proposal_json,
                 llm_metadata_json = :llm_metadata_json,
                 created_at = :created_at,
                 updated_at = :updated_at
             WHERE proposal_id = :proposal_id'
        );
        $stmt->execute([
            ':proposal_id' => $proposalId,
            ':status' => (string) ($proposal['status'] ?? 'draft'),
            ':source_run_id' => (string) ($proposal['source_run_id'] ?? ''),
            ':base_model_id' => (string) ($proposal['base_model_id'] ?? ''),
            ':proposal_json' => (string) json_encode($proposal['proposal'] ?? [], JSON_UNESCAPED_UNICODE),
            ':llm_metadata_json' => (string) json_encode($proposal['llm_metadata'] ?? [], JSON_UNESCAPED_UNICODE),
            ':created_at' => (string) ($proposal['created_at'] ?? ''),
            ':updated_at' => (string) ($proposal['updated_at'] ?? ''),
        ]);
    }

    public function appendExecutionRequest(array $request): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO execution_requests (request_id, type, status, config_json, created_at, updated_at, claimed_by_worker, claimed_at, heartbeat_at, attempts, result_summary_json, result_artifacts_json, error_summary)
             VALUES (:request_id, :type, :status, :config_json, :created_at, :updated_at, :claimed_by_worker, :claimed_at, :heartbeat_at, :attempts, :result_summary_json, :result_artifacts_json, :error_summary)'
        );
        $stmt->execute([
            ':request_id' => (string) ($request['request_id'] ?? ''),
            ':type' => (string) ($request['type'] ?? ''),
            ':status' => (string) ($request['status'] ?? 'pending'),
            ':config_json' => (string) json_encode($request['config'] ?? [], JSON_UNESCAPED_UNICODE),
            ':created_at' => (string) ($request['created_at'] ?? ''),
            ':updated_at' => (string) ($request['updated_at'] ?? ''),
            ':claimed_by_worker' => isset($request['claimed_by_worker']) && $request['claimed_by_worker'] !== '' ? (string) $request['claimed_by_worker'] : null,
            ':claimed_at' => isset($request['claimed_at']) && $request['claimed_at'] !== '' ? (string) $request['claimed_at'] : null,
            ':heartbeat_at' => isset($request['heartbeat_at']) && $request['heartbeat_at'] !== '' ? (string) $request['heartbeat_at'] : null,
            ':attempts' => (int) ($request['attempts'] ?? 0),
            ':result_summary_json' => (string) json_encode($request['result_summary'] ?? [], JSON_UNESCAPED_UNICODE),
            ':result_artifacts_json' => (string) json_encode($request['result_artifacts'] ?? [], JSON_UNESCAPED_UNICODE),
            ':error_summary' => isset($request['error_summary']) && $request['error_summary'] !== '' ? (string) $request['error_summary'] : null,
        ]);
    }

    public function replaceExecutionRequest(string $requestId, array $request): void
    {
        $stmt = $this->pdo->prepare(
            'UPDATE execution_requests
             SET type = :type,
                 status = :status,
                 config_json = :config_json,
                 created_at = :created_at,
                 updated_at = :updated_at,
                 claimed_by_worker = :claimed_by_worker,
                 claimed_at = :claimed_at,
                 heartbeat_at = :heartbeat_at,
                 attempts = :attempts,
                 result_summary_json = :result_summary_json,
                 result_artifacts_json = :result_artifacts_json,
                 error_summary = :error_summary
             WHERE request_id = :request_id'
        );
        $stmt->execute([
            ':request_id' => $requestId,
            ':type' => (string) ($request['type'] ?? ''),
            ':status' => (string) ($request['status'] ?? 'pending'),
            ':config_json' => (string) json_encode($request['config'] ?? [], JSON_UNESCAPED_UNICODE),
            ':created_at' => (string) ($request['created_at'] ?? ''),
            ':updated_at' => (string) ($request['updated_at'] ?? ''),
            ':claimed_by_worker' => isset($request['claimed_by_worker']) && $request['claimed_by_worker'] !== '' ? (string) $request['claimed_by_worker'] : null,
            ':claimed_at' => isset($request['claimed_at']) && $request['claimed_at'] !== '' ? (string) $request['claimed_at'] : null,
            ':heartbeat_at' => isset($request['heartbeat_at']) && $request['heartbeat_at'] !== '' ? (string) $request['heartbeat_at'] : null,
            ':attempts' => (int) ($request['attempts'] ?? 0),
            ':result_summary_json' => (string) json_encode($request['result_summary'] ?? [], JSON_UNESCAPED_UNICODE),
            ':result_artifacts_json' => (string) json_encode($request['result_artifacts'] ?? [], JSON_UNESCAPED_UNICODE),
            ':error_summary' => isset($request['error_summary']) && $request['error_summary'] !== '' ? (string) $request['error_summary'] : null,
        ]);
    }

    public function resetAll(): void
    {
        $this->pdo->beginTransaction();
        try {
            $this->pdo->exec('DELETE FROM events');
            $this->pdo->exec('DELETE FROM metrics');
            $this->pdo->exec('DELETE FROM artifacts');
            $this->pdo->exec('DELETE FROM model_proposals');
            $this->pdo->exec('DELETE FROM runs');
            $this->pdo->commit();
        } catch (\Throwable $error) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            throw $error;
        }
    }

    private function initializeSchema(): void
    {
        $this->pdo->exec(
            'CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                code_version TEXT NOT NULL,
                generation INTEGER NOT NULL,
                heartbeat_at TEXT NULL,
                metadata_json TEXT NOT NULL
            )'
        );
        $this->pdo->exec(
            'CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                label TEXT NOT NULL,
                level TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                details_json TEXT NOT NULL
            )'
        );
        $this->pdo->exec(
            'CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                generation INTEGER NOT NULL,
                metrics_json TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )'
        );
        $this->pdo->exec(
            'CREATE TABLE IF NOT EXISTS artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                uri TEXT NOT NULL,
                checksum TEXT NULL,
                storage TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )'
        );
        $this->pdo->exec(
            'CREATE TABLE IF NOT EXISTS model_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                source_run_id TEXT NOT NULL,
                base_model_id TEXT NOT NULL,
                proposal_json TEXT NOT NULL,
                llm_metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )'
        );
        $this->pdo->exec(
            'CREATE TABLE IF NOT EXISTS execution_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                config_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                claimed_by_worker TEXT NULL,
                claimed_at TEXT NULL,
                heartbeat_at TEXT NULL,
                attempts INTEGER NOT NULL,
                result_summary_json TEXT NOT NULL,
                result_artifacts_json TEXT NOT NULL,
                error_summary TEXT NULL
            )'
        );
    }

    private function decodeArray(string $json): array
    {
        $decoded = json_decode($json, true);
        return is_array($decoded) ? $decoded : [];
    }
}
