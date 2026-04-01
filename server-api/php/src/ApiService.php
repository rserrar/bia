<?php

declare(strict_types=1);

namespace V2ServerApi;

use InvalidArgumentException;
use RuntimeException;

final class ApiService
{
    private const VALID_STATUSES = ['queued', 'running', 'retrying', 'completed', 'failed', 'cancelled'];
    private const VALID_ARTIFACT_STORAGES = ['drive', 'cloud', 'local'];
    private const VALID_PROPOSAL_STATUSES = ['draft', 'queued_phase0', 'validated_phase0', 'accepted', 'rejected', 'training', 'trained'];
    private const VALID_EXECUTION_REQUEST_STATUSES = ['pending', 'claimed', 'running', 'completed', 'failed', 'cancelled'];

    private $store;

    public function __construct($store)
    {
        $this->store = $store;
    }

    public function createRun(string $codeVersion, array $metadata = []): array
    {
        $now = $this->nowIso();
        $run = [
            'run_id' => 'run_' . substr(bin2hex(random_bytes(8)), 0, 12),
            'status' => 'queued',
            'created_at' => $now,
            'updated_at' => $now,
            'code_version' => $codeVersion,
            'generation' => 0,
            'heartbeat_at' => null,
            'metadata' => $metadata,
        ];
        $this->store->upsertRun($run);
        return $run;
    }

    public function updateStatus(string $runId, string $status, ?int $generation): array
    {
        $this->assertStatus($status);
        $state = $this->store->readAll();
        if (!isset($state['runs'][$runId])) {
            throw new RuntimeException('run not found');
        }
        $run = $state['runs'][$runId];
        $run['status'] = $status;
        $run['updated_at'] = $this->nowIso();
        if ($generation !== null) {
            $run['generation'] = $generation;
        }
        $this->store->upsertRun($run);
        return $run;
    }

    public function heartbeat(string $runId): array
    {
        $state = $this->store->readAll();
        if (!isset($state['runs'][$runId])) {
            throw new RuntimeException('run not found');
        }
        $run = $state['runs'][$runId];
        $run['heartbeat_at'] = $this->nowIso();
        $run['updated_at'] = $run['heartbeat_at'];
        if ($run['status'] === 'queued') {
            $run['status'] = 'running';
        }
        $this->store->upsertRun($run);
        return $run;
    }

    public function addEvent(string $runId, string $eventType, string $label, array $details = []): array
    {
        $event = [
            'run_id' => $runId,
            'event_type' => $eventType,
            'label' => $label,
            'level' => 'info',
            'timestamp' => $this->nowIso(),
            'details' => $details,
        ];
        $this->store->appendEvent($event);
        return $event;
    }

    public function addMetric(string $runId, string $modelId, int $generation, array $metrics): array
    {
        $metric = [
            'run_id' => $runId,
            'model_id' => $modelId,
            'generation' => $generation,
            'metrics' => $metrics,
            'timestamp' => $this->nowIso(),
        ];
        $this->store->appendMetric($metric);
        return $metric;
    }

    public function addArtifact(string $runId, string $artifactType, string $uri, string $storage = 'drive', ?string $checksum = null, array $metadata = []): array
    {
        $artifactId = (string) ($metadata['artifact_id'] ?? ('art_' . substr(bin2hex(random_bytes(8)), 0, 12)));
        $metadata['artifact_id'] = $artifactId;
        $artifact = [
            'run_id' => $runId,
            'artifact_type' => $artifactType,
            'uri' => $uri,
            'checksum' => $checksum,
            'storage' => $storage,
            'metadata' => $metadata,
            'timestamp' => $this->nowIso(),
        ];
        $this->store->appendArtifact($artifact);
        return $artifact;
    }

    public function uploadArtifact(string $runId, string $artifactType, string $fileName, string $contentBase64, array $metadata = []): array
    {
        $artifactId = 'art_' . substr(bin2hex(random_bytes(8)), 0, 12);
        $safeFileName = preg_replace('/[^A-Za-z0-9._-]/', '_', $fileName) ?: ($artifactId . '.bin');
        $decoded = base64_decode($contentBase64, true);
        if ($decoded === false) {
            throw new RuntimeException('invalid base64 artifact content');
        }
        $storageDir = $this->artifactStorageDir() . DIRECTORY_SEPARATOR . $runId;
        if (!is_dir($storageDir) && !mkdir($storageDir, 0777, true) && !is_dir($storageDir)) {
            throw new RuntimeException('could not create artifact storage directory');
        }
        $absolutePath = $storageDir . DIRECTORY_SEPARATOR . $artifactId . '__' . $safeFileName;
        if (file_put_contents($absolutePath, $decoded) === false) {
            throw new RuntimeException('could not persist artifact content');
        }
        $checksum = hash_file('sha256', $absolutePath) ?: null;
        $metadata = array_merge(
            $metadata,
            [
                'artifact_id' => $artifactId,
                'file_name' => $safeFileName,
                'storage_backend' => 'server',
                'download_url' => '/artifacts/' . $artifactId . '/download',
                'availability_status' => 'available',
            ]
        );
        return $this->addArtifact($runId, $artifactType, $absolutePath, 'server', $checksum, $metadata);
    }

    public function createExecutionRequest(string $type, array $config = []): array
    {
        $normalizedConfig = $this->normalizeExecutionRequestConfig($type, $config);
        $request = [
            'request_id' => 'req_' . substr(bin2hex(random_bytes(8)), 0, 12),
            'type' => $type,
            'status' => 'pending',
            'config' => $normalizedConfig,
            'created_at' => $this->nowIso(),
            'updated_at' => $this->nowIso(),
            'claimed_by_worker' => null,
            'claimed_at' => null,
            'heartbeat_at' => null,
            'attempts' => 0,
            'result_summary' => [],
            'result_artifacts' => [],
            'error_summary' => null,
        ];
        $this->store->appendExecutionRequest($request);
        return $this->normalizeExecutionRequestView($request);
    }

    public function listExecutionRequests(int $limit = 100, ?string $status = null): array
    {
        $state = $this->store->readAll();
        $requests = array_values(is_array($state['execution_requests'] ?? null) ? $state['execution_requests'] : []);
        if ($status !== null && $status !== '') {
            $requests = array_values(array_filter($requests, static fn(array $request): bool => (string) ($request['status'] ?? '') === $status));
        }
        usort($requests, static fn(array $a, array $b): int => (strtotime((string) ($b['updated_at'] ?? '')) ?: 0) <=> (strtotime((string) ($a['updated_at'] ?? '')) ?: 0));
        if ($limit > 0 && count($requests) > $limit) {
            $requests = array_slice($requests, 0, $limit);
        }
        return array_map(fn(array $request): array => $this->normalizeExecutionRequestView($request), $requests);
    }

    public function getExecutionRequest(string $requestId): array
    {
        return $this->normalizeExecutionRequestView($this->getRawExecutionRequest($requestId));
    }

    public function updateExecutionRequestConfig(string $requestId, array $configUpdates): array
    {
        $request = $this->getRawExecutionRequest($requestId);
        $status = (string) ($request['status'] ?? '');
        if (in_array($status, ['completed', 'failed', 'cancelled'], true)) {
            throw new RuntimeException('cannot update terminal execution request');
        }
        $currentConfig = is_array($request['config'] ?? null) ? $request['config'] : [];
        $request['config'] = $this->normalizeExecutionRequestConfig((string) ($request['type'] ?? ''), array_merge($currentConfig, $configUpdates));
        $request['updated_at'] = $this->nowIso();
        $this->store->replaceExecutionRequest($requestId, $request);
        return $this->normalizeExecutionRequestView($request);
    }

    public function getExecutionRequestAutopsy(string $requestId, int $timelineLimit = 40): array
    {
        $request = $this->getExecutionRequest($requestId);
        $resultSummary = is_array($request['result_summary'] ?? null) ? $request['result_summary'] : [];
        $runIds = array_values(array_filter(
            array_map(static fn($runId): string => is_string($runId) ? trim($runId) : '', (array) ($request['run_ids'] ?? [])),
            static fn(string $runId): bool => $runId !== ''
        ));
        $lifecycle = $this->buildExecutionLifecycle($request);
        $runs = [];
        foreach ($runIds as $runId) {
            $runs[] = $this->buildExecutionRunAutopsy($runId, $timelineLimit);
        }
        $status = (string) ($request['status'] ?? '');
        $effectiveStage = in_array($status, ['completed', 'failed', 'cancelled'], true)
            ? $status
            : (string) ($request['current_stage'] ?? '');
        $effectiveStageLabel = in_array($status, ['completed', 'failed', 'cancelled'], true)
            ? $this->executionFinalStatusLabel($status)
            : (string) ($request['current_stage_label'] ?? '');
        $outcome = $this->deriveExecutionOutcome($request, $runs, $resultSummary);
        $referenceContext = $this->deriveExecutionReferenceContext($request, $runs, $resultSummary);

        return [
            'request_id' => (string) ($request['request_id'] ?? ''),
            'status' => $status,
            'type' => (string) ($request['type'] ?? ''),
            'type_description' => (string) ($request['type_description'] ?? ''),
            'config' => is_array($request['config'] ?? null) ? $request['config'] : [],
            'worker' => [
                'claimed_by_worker' => (string) ($request['claimed_by_worker'] ?? ''),
                'attempts' => (int) ($request['attempts'] ?? 0),
                'claimed_at' => (string) ($request['claimed_at'] ?? ''),
                'heartbeat_at' => (string) ($request['heartbeat_at'] ?? ''),
            ],
            'timing' => [
                'created_at' => (string) ($request['created_at'] ?? ''),
                'started_at' => (string) ($request['started_at'] ?? ''),
                'completed_at' => (string) ($request['completed_at'] ?? ''),
                'elapsed_seconds' => $request['elapsed_seconds'] ?? null,
            ],
            'progress' => is_array($request['progress'] ?? null) ? $request['progress'] : [],
            'run_ids' => $runIds,
            'current_run_id' => (string) ($request['current_run_id'] ?? ''),
            'current_stage' => $effectiveStage,
            'current_stage_label' => $effectiveStageLabel,
            'error_summary' => $request['error_summary'] ?? null,
            'outcome' => $outcome,
            'reference_context' => $referenceContext,
            'lifecycle' => $lifecycle,
            'log_excerpt' => $this->buildExecutionLogExcerpt((string) ($resultSummary['output_tail'] ?? '')),
            'runs' => $runs,
        ];
    }

    public function listPendingExecutionRequests(int $limit = 100, int $staleAfterSeconds = 120): array
    {
        $now = time();
        $eligible = [];
        foreach ($this->listExecutionRequests(1000) as $request) {
            $status = (string) ($request['status'] ?? '');
            if ($status === 'pending') {
                $eligible[] = $request;
                continue;
            }
            if (!in_array($status, ['claimed', 'running'], true)) {
                continue;
            }
            $heartbeatAt = strtotime((string) ($request['heartbeat_at'] ?? '')) ?: 0;
            if ($heartbeatAt > 0 && ($now - $heartbeatAt) > $staleAfterSeconds) {
                $request['status'] = 'pending';
                $request['updated_at'] = $this->nowIso();
                $request['claimed_by_worker'] = null;
                $request['claimed_at'] = null;
                $this->store->replaceExecutionRequest((string) $request['request_id'], $request);
                $eligible[] = $request;
            }
        }
        usort($eligible, static fn(array $a, array $b): int => (strtotime((string) ($a['created_at'] ?? '')) ?: 0) <=> (strtotime((string) ($b['created_at'] ?? '')) ?: 0));
        if ($limit > 0 && count($eligible) > $limit) {
            $eligible = array_slice($eligible, 0, $limit);
        }
        return array_map(fn(array $request): array => $this->normalizeExecutionRequestView($request), $eligible);
    }

    public function claimExecutionRequest(string $requestId, string $workerId, int $staleAfterSeconds = 120): array
    {
        $request = $this->getExecutionRequest($requestId);
        $status = (string) ($request['status'] ?? '');
        $heartbeatAt = strtotime((string) ($request['heartbeat_at'] ?? '')) ?: 0;
        $isStaleClaim = in_array($status, ['claimed', 'running'], true) && $heartbeatAt > 0 && ((time() - $heartbeatAt) > $staleAfterSeconds);
        if (!in_array($status, ['pending'], true) && !$isStaleClaim) {
            throw new RuntimeException('execution_request not claimable');
        }
        $request['status'] = 'claimed';
        $request['claimed_by_worker'] = $workerId;
        $request['claimed_at'] = $this->nowIso();
        $request['heartbeat_at'] = $request['claimed_at'];
        $request['updated_at'] = $request['claimed_at'];
        $request['attempts'] = (int) ($request['attempts'] ?? 0) + 1;
        $this->store->replaceExecutionRequest($requestId, $request);
        return $this->normalizeExecutionRequestView($request);
    }

    public function heartbeatExecutionRequest(string $requestId, string $workerId, array $resultSummary = []): array
    {
        $request = $this->getExecutionRequest($requestId);
        $request['heartbeat_at'] = $this->nowIso();
        $request['updated_at'] = $request['heartbeat_at'];
        $request['claimed_by_worker'] = $workerId;
        if (!empty($resultSummary)) {
            $currentSummary = is_array($request['result_summary'] ?? null) ? $request['result_summary'] : [];
            $request['result_summary'] = array_merge($currentSummary, $resultSummary);
        }
        $this->store->replaceExecutionRequest($requestId, $request);
        return $this->normalizeExecutionRequestView($request);
    }

    public function startExecutionRequest(string $requestId, string $workerId): array
    {
        return $this->updateExecutionRequestStatus($requestId, 'running', $workerId);
    }

    public function completeExecutionRequest(string $requestId, array $resultSummary = [], array $resultArtifacts = []): array
    {
        return $this->updateExecutionRequestStatus($requestId, 'completed', null, $resultSummary, $resultArtifacts, null);
    }

    public function failExecutionRequest(string $requestId, string $errorSummary, array $resultSummary = []): array
    {
        return $this->updateExecutionRequestStatus($requestId, 'failed', null, $resultSummary, [], $errorSummary);
    }

    public function cancelExecutionRequest(string $requestId): array
    {
        return $this->updateExecutionRequestStatus($requestId, 'cancelled');
    }

    public function getRun(string $runId): array
    {
        $state = $this->store->readAll();
        if (!isset($state['runs'][$runId])) {
            throw new RuntimeException('run not found');
        }
        return $state['runs'][$runId];
    }

    public function listRuns(int $limit = 100): array
    {
        $state = $this->store->readAll();
        $runs = array_values(is_array($state['runs'] ?? null) ? $state['runs'] : []);
        usort(
            $runs,
            static function (array $a, array $b): int {
                $aTs = strtotime((string) ($a['updated_at'] ?? '')) ?: 0;
                $bTs = strtotime((string) ($b['updated_at'] ?? '')) ?: 0;
                return $bTs <=> $aTs;
            }
        );
        if ($limit > 0 && count($runs) > $limit) {
            $runs = array_slice($runs, 0, $limit);
        }
        return $runs;
    }

    public function listEvents(int $limit = 200): array
    {
        $state = $this->store->readAll();
        $events = array_values(is_array($state['events'] ?? null) ? $state['events'] : []);
        usort(
            $events,
            static function (array $a, array $b): int {
                $aTs = strtotime((string) ($a['timestamp'] ?? '')) ?: 0;
                $bTs = strtotime((string) ($b['timestamp'] ?? '')) ?: 0;
                return $bTs <=> $aTs; // Descending
            }
        );
        if ($limit > 0 && count($events) > $limit) {
            $events = array_slice($events, 0, $limit);
        }
        return $events;
    }

    public function listMetrics(int $limit = 200): array
    {
        $state = $this->store->readAll();
        $metrics = array_values(is_array($state['metrics'] ?? null) ? $state['metrics'] : []);
        usort(
            $metrics,
            static function (array $a, array $b): int {
                $aTs = strtotime((string) ($a['timestamp'] ?? '')) ?: 0;
                $bTs = strtotime((string) ($b['timestamp'] ?? '')) ?: 0;
                return $bTs <=> $aTs; // Descending
            }
        );
        if ($limit > 0 && count($metrics) > $limit) {
            $metrics = array_slice($metrics, 0, $limit);
        }
        return $metrics;
    }

    public function getSummary(string $runId): array
    {
        $state = $this->store->readAll();
        if (!isset($state['runs'][$runId])) {
            throw new RuntimeException('run not found');
        }
        $events = array_values(array_filter($state['events'], static fn(array $event): bool => $event['run_id'] === $runId));
        $metrics = array_values(array_filter($state['metrics'], static fn(array $metric): bool => $metric['run_id'] === $runId));
        $artifacts = array_values(array_filter($state['artifacts'], static fn(array $artifact): bool => $artifact['run_id'] === $runId));
        $proposals = array_values(array_filter(
            is_array($state['model_proposals'] ?? null) ? $state['model_proposals'] : [],
            static fn(array $proposal): bool => (string) ($proposal['source_run_id'] ?? '') === $runId
        ));
        $proposalsByStatus = [];
        foreach ($proposals as $proposal) {
            $status = (string) ($proposal['status'] ?? 'unknown');
            $proposalsByStatus[$status] = (int) ($proposalsByStatus[$status] ?? 0) + 1;
        }
        $champion = $this->getChampionRun($runId, 5);

        return [
            'run' => $state['runs'][$runId],
            'counts' => [
                'events' => count($events),
                'metrics' => count($metrics),
                'artifacts' => count($artifacts),
                'proposals' => count($proposals),
            ],
            'proposals_by_status' => $proposalsByStatus,
            'champion' => $champion['champion'] ?? null,
            'summary_text' => $this->buildRunSummaryText($proposalsByStatus, $champion['champion'] ?? null, count($artifacts)),
            'latest_event' => count($events) > 0 ? $events[count($events) - 1] : null,
            'latest_metric' => count($metrics) > 0 ? $metrics[count($metrics) - 1] : null,
            'latest_artifact' => count($artifacts) > 0 ? $artifacts[count($artifacts) - 1] : null,
        ];
    }

    public function listUiProposals(int $limit = 100): array
    {
        $proposals = $this->listModelProposals($limit);
        $enriched = [];
        foreach ($proposals as $proposal) {
            $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
            $artifacts = $this->getModelArtifacts((string) ($proposal['proposal_id'] ?? ''))['artifacts'];
            $primaryArtifact = count($artifacts) > 0 && is_array($artifacts[0]) ? $artifacts[0] : [];
            $enriched[] = [
                'proposal_id' => (string) ($proposal['proposal_id'] ?? ''),
                'status' => (string) ($proposal['status'] ?? ''),
                'source_run_id' => (string) ($proposal['source_run_id'] ?? ''),
                'base_model_id' => (string) ($proposal['base_model_id'] ?? ''),
                'updated_at' => (string) ($proposal['updated_at'] ?? ''),
                'trained_model_uri' => $llmMetadata['trained_model_uri'] ?? null,
                'training_kpis' => is_array($llmMetadata['training_kpis'] ?? null) ? $llmMetadata['training_kpis'] : [],
                'prompt_audit' => is_array($llmMetadata['prompt_audit'] ?? null) ? $llmMetadata['prompt_audit'] : [],
                'artifacts' => $artifacts,
                'primary_artifact' => $primaryArtifact,
                'resume' => [
                    'resumable' => (bool) ($llmMetadata['resumable'] ?? false),
                    'last_epoch_completed' => $llmMetadata['last_epoch_completed'] ?? null,
                    'last_checkpoint_epoch' => $llmMetadata['last_checkpoint_epoch'] ?? null,
                    'resume_attempts' => $llmMetadata['resume_attempts'] ?? null,
                ],
                'champion' => [
                    'active' => (bool) ($llmMetadata['champion_active'] ?? false),
                    'scope' => (string) ($llmMetadata['champion_scope'] ?? ''),
                    'score' => $llmMetadata['champion_score'] ?? null,
                    'policy_version' => (string) ($llmMetadata['champion_policy_version'] ?? ''),
                    'policy_profile' => (string) ($llmMetadata['champion_policy_profile'] ?? ''),
                ],
            ];
        }
        return $enriched;
    }

    public function getChampionRun(string $runId, int $topN = 5): array
    {
        $state = $this->store->readAll();
        if (!isset($state['runs'][$runId])) {
            throw new RuntimeException('run not found');
        }
        $policy = $this->policyConfigForProfile(getenv('V2_SELECTION_POLICY_PROFILE') ?: 'default');
        $proposals = $this->listModelProposals(1000);
        $filtered = array_values(array_filter(
            $proposals,
            static fn(array $proposal): bool => (string) ($proposal['source_run_id'] ?? '') === $runId
        ));
        return $this->buildChampionPayload($filtered, 'run', $runId, $policy, $topN);
    }

    public function getChampionGlobal(int $topN = 5): array
    {
        $policy = $this->policyConfigForProfile(getenv('V2_SELECTION_POLICY_PROFILE') ?: 'default');
        $proposals = $this->listModelProposals(1000);
        return $this->buildChampionPayload($proposals, 'global', null, $policy, $topN);
    }

    public function getRunReferences(string $runId, int $limit = 10): array
    {
        $proposal = null;
        foreach ($this->listModelProposals(1000) as $candidate) {
            if ((string) ($candidate['source_run_id'] ?? '') !== $runId) {
                continue;
            }
            $llmMetadata = is_array($candidate['llm_metadata'] ?? null) ? $candidate['llm_metadata'] : [];
            $promptAudit = is_array($llmMetadata['prompt_audit'] ?? null) ? $llmMetadata['prompt_audit'] : [];
            if (!empty($promptAudit)) {
                $proposal = $candidate;
                break;
            }
        }
        if ($proposal === null) {
            return ['run_id' => $runId, 'references' => [], 'fallback_used' => false];
        }
        $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
        $promptAudit = is_array($llmMetadata['prompt_audit'] ?? null) ? $llmMetadata['prompt_audit'] : [];
        $selected = array_values(array_slice(
            is_array($promptAudit['reference_models_selected'] ?? null) ? $promptAudit['reference_models_selected'] : [],
            0,
            max(1, $limit)
        ));
        foreach ($selected as $index => $reference) {
            if (!is_array($reference)) {
                continue;
            }
            $selected[$index]['role'] = $this->inferReferenceRole($reference, $index, count($selected));
        }
        return [
            'run_id' => $runId,
            'reference_policy_version' => (string) ($promptAudit['reference_policy_version'] ?? ''),
            'reference_models_count' => (int) ($promptAudit['reference_models_count'] ?? count($selected)),
            'references' => $selected,
            'fallback_used' => count($selected) > 0 && (string) (($selected[0]['selection_reason'] ?? '')) === 'local_fallback',
        ];
    }

    public function getModelsShortlist(int $limit = 10): array
    {
        $payload = $this->getChampionGlobal(max(1, $limit));
        $shortlist = [];
        foreach (array_slice($payload['top_candidates'] ?? [], 0, max(1, $limit)) as $entry) {
            if (!is_array($entry)) {
                continue;
            }
            $proposal = is_array($entry['proposal'] ?? null) ? $entry['proposal'] : [];
            $decision = is_array($entry['decision'] ?? null) ? $entry['decision'] : [];
            $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
            $trainingKpis = is_array($llmMetadata['training_kpis'] ?? null) ? $llmMetadata['training_kpis'] : [];
            $shortlist[] = [
                'proposal_id' => (string) ($proposal['proposal_id'] ?? ''),
                'source_run_id' => (string) ($proposal['source_run_id'] ?? ''),
                'status' => (string) ($proposal['status'] ?? ''),
                'score' => $decision['score'] ?? null,
                'selection_reason' => (string) ($decision['selection_reason'] ?? ''),
                'score_breakdown' => $decision['score_breakdown'] ?? [],
                'trained_model_uri' => $llmMetadata['trained_model_uri'] ?? null,
                'training_kpis' => $trainingKpis,
                'rationale' => $this->buildShortRationale($decision, $trainingKpis),
                'primary_kpi' => $trainingKpis['val_loss_total'] ?? null,
                'artifacts' => $this->getModelArtifacts((string) ($proposal['proposal_id'] ?? ''))['artifacts'],
            ];
        }
        return [
            'policy_version' => $payload['policy_version'] ?? 'selection_policy_v1_1',
            'policy_profile' => $payload['policy_profile'] ?? 'default',
            'shortlist' => $shortlist,
        ];
    }

    public function getModelArtifacts(string $proposalId): array
    {
        $proposal = $this->getModelProposal($proposalId);
        $runId = (string) ($proposal['source_run_id'] ?? '');
        $state = $this->store->readAll();
        $artifacts = array_values(array_filter(
            is_array($state['artifacts'] ?? null) ? $state['artifacts'] : [],
            static function (array $artifact) use ($proposalId, $runId): bool {
                $metadata = is_array($artifact['metadata'] ?? null) ? $artifact['metadata'] : [];
                return (string) ($artifact['run_id'] ?? '') === $runId
                    && (string) ($metadata['proposal_id'] ?? '') === $proposalId;
            }
        ));

        return [
            'proposal_id' => $proposalId,
            'artifacts' => array_map(fn(array $artifact): array => $this->normalizeArtifactView($artifact), $artifacts),
        ];
    }

    public function getRunTimeline(string $runId, int $limit = 200): array
    {
        $state = $this->store->readAll();
        if (!isset($state['runs'][$runId])) {
            throw new RuntimeException('run not found');
        }
        $events = $this->listRunEvents($runId, $limit);
        $timeline = [];
        foreach ($events as $event) {
            $details = is_array($event['details'] ?? null) ? $event['details'] : [];
            $timeline[] = [
                'timestamp' => (string) ($event['timestamp'] ?? ''),
                'type' => (string) ($event['event_type'] ?? ''),
                'label' => (string) ($event['label'] ?? ''),
                'level' => (string) ($event['level'] ?? 'info'),
                'details' => $details,
                'proposal_id' => (string) ($details['proposal_id'] ?? ''),
                'epoch' => isset($details['epoch']) ? (int) $details['epoch'] : null,
            ];
        }
        return [
            'run_id' => $runId,
            'timeline' => $timeline,
        ];
    }

    public function getModelDetailView(string $proposalId): array
    {
        $proposal = $this->getModelProposal($proposalId);
        $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
        $trainingKpis = is_array($llmMetadata['training_kpis'] ?? null) ? $llmMetadata['training_kpis'] : [];
        $promptAudit = is_array($llmMetadata['prompt_audit'] ?? null) ? $llmMetadata['prompt_audit'] : [];
        $score = isset($llmMetadata['champion_score']) ? (float) $llmMetadata['champion_score'] : null;
        $decision = $this->evaluateProposalSelection($proposal, $this->policyConfigForProfile(getenv('V2_SELECTION_POLICY_PROFILE') ?: 'default'));
        return [
            'proposal_id' => (string) ($proposal['proposal_id'] ?? ''),
            'source_run_id' => (string) ($proposal['source_run_id'] ?? ''),
            'base_model_id' => (string) ($proposal['base_model_id'] ?? ''),
            'status' => (string) ($proposal['status'] ?? ''),
            'updated_at' => (string) ($proposal['updated_at'] ?? ''),
            'trained_model_uri' => $llmMetadata['trained_model_uri'] ?? null,
            'training_kpis' => $trainingKpis,
            'prompt_audit' => $promptAudit,
            'phase0_auto' => is_array($llmMetadata['phase0_auto'] ?? null) ? $llmMetadata['phase0_auto'] : [],
            'phase0_rejected_reason' => (string) ($llmMetadata['phase0_rejected_reason'] ?? ''),
            'champion' => [
                'active' => (bool) ($llmMetadata['champion_active'] ?? false),
                'scope' => (string) ($llmMetadata['champion_scope'] ?? ''),
                'score' => $score,
                'policy_version' => (string) ($llmMetadata['champion_policy_version'] ?? ''),
                'policy_profile' => (string) ($llmMetadata['champion_policy_profile'] ?? ''),
            ],
            'artifacts' => $this->getModelArtifacts($proposalId)['artifacts'],
            'resume_state' => [
                'resumable' => (bool) ($llmMetadata['resumable'] ?? false),
                'last_epoch_completed' => $llmMetadata['last_epoch_completed'] ?? null,
                'last_checkpoint_artifact_id' => $llmMetadata['last_checkpoint_artifact_id'] ?? null,
                'last_checkpoint_epoch' => $llmMetadata['last_checkpoint_epoch'] ?? null,
                'last_checkpoint_local_path' => $llmMetadata['last_checkpoint_local_path'] ?? null,
                'resume_attempts' => $llmMetadata['resume_attempts'] ?? 0,
                'resumed_from_checkpoint' => (bool) ($llmMetadata['resumed_from_checkpoint'] ?? false),
                'resume_checkpoint_uri' => $llmMetadata['resume_checkpoint_uri'] ?? null,
                'training_interrupted_at' => $llmMetadata['training_interrupted_at'] ?? null,
                'resume_history' => is_array($llmMetadata['resume_history'] ?? null) ? $llmMetadata['resume_history'] : [],
            ],
            'selection_view' => $decision,
            'proposal_payload' => is_array($proposal['proposal'] ?? null) ? $proposal['proposal'] : [],
        ];
    }

    public function compareModels(string $leftProposalId, string $rightProposalId): array
    {
        $left = $this->getModelDetailView($leftProposalId);
        $right = $this->getModelDetailView($rightProposalId);

        $leftKpis = is_array($left['training_kpis'] ?? null) ? $left['training_kpis'] : [];
        $rightKpis = is_array($right['training_kpis'] ?? null) ? $right['training_kpis'] : [];
        $leftSelection = is_array($left['selection_view'] ?? null) ? $left['selection_view'] : [];
        $rightSelection = is_array($right['selection_view'] ?? null) ? $right['selection_view'] : [];

        $comparison = [
            'score_delta' => $this->deltaValue($leftSelection['score'] ?? null, $rightSelection['score'] ?? null),
            'val_loss_delta' => $this->deltaValue($leftKpis['val_loss_total'] ?? null, $rightKpis['val_loss_total'] ?? null),
            'training_time_delta' => $this->deltaValue($leftKpis['training_time_seconds'] ?? null, $rightKpis['training_time_seconds'] ?? null),
            'train_loss_delta' => $this->deltaValue($leftKpis['train_loss'] ?? null, $rightKpis['train_loss'] ?? null),
        ];

        return [
            'left' => $left,
            'right' => $right,
            'comparison' => $comparison,
            'better_by' => [
                'score' => $this->winnerLabel($leftSelection['score'] ?? null, $rightSelection['score'] ?? null, true),
                'val_loss_total' => $this->winnerLabel($leftKpis['val_loss_total'] ?? null, $rightKpis['val_loss_total'] ?? null, false),
                'training_time_seconds' => $this->winnerLabel($leftKpis['training_time_seconds'] ?? null, $rightKpis['training_time_seconds'] ?? null, false),
                'train_loss' => $this->winnerLabel($leftKpis['train_loss'] ?? null, $rightKpis['train_loss'] ?? null, false),
            ],
        ];
    }

    public function getArtifactDownloadInfo(string $artifactId): array
    {
        $state = $this->store->readAll();
        $artifacts = is_array($state['artifacts'] ?? null) ? $state['artifacts'] : [];
        foreach ($artifacts as $artifact) {
            $metadata = is_array($artifact['metadata'] ?? null) ? $artifact['metadata'] : [];
            if ((string) ($metadata['artifact_id'] ?? '') !== $artifactId) {
                continue;
            }
            $normalized = $this->normalizeArtifactView($artifact);
            if ((string) ($normalized['storage_backend'] ?? '') !== 'server') {
                throw new RuntimeException('artifact is not server-downloadable');
            }
            if ((string) ($normalized['availability_status'] ?? '') !== 'available') {
                throw new RuntimeException('artifact not available');
            }
            return [
                'path' => (string) ($artifact['uri'] ?? ''),
                'file_name' => (string) ($metadata['file_name'] ?? basename((string) ($artifact['uri'] ?? 'artifact.bin'))),
                'mime_type' => 'application/octet-stream',
            ];
        }
        throw new RuntimeException('artifact not found');
    }

    public function listRunEvents(string $runId, int $limit = 200): array
    {
        $state = $this->store->readAll();
        if (!isset($state['runs'][$runId])) {
            throw new RuntimeException('run not found');
        }
        $events = array_values(array_filter($state['events'], static fn(array $event): bool => $event['run_id'] === $runId));
        usort(
            $events,
            static function (array $a, array $b): int {
                $aTs = strtotime((string) ($a['timestamp'] ?? '')) ?: 0;
                $bTs = strtotime((string) ($b['timestamp'] ?? '')) ?: 0;
                return $aTs <=> $bTs;
            }
        );
        if ($limit > 0 && count($events) > $limit) {
            $events = array_slice($events, -$limit);
        }
        return $events;
    }

    public function listRunArtifacts(string $runId, int $limit = 200): array
    {
        $state = $this->store->readAll();
        if (!isset($state['runs'][$runId])) {
            throw new RuntimeException('run not found');
        }
        $artifacts = array_values(array_filter(
            is_array($state['artifacts'] ?? null) ? $state['artifacts'] : [],
            static fn(array $artifact): bool => (string) ($artifact['run_id'] ?? '') === $runId
        ));
        usort(
            $artifacts,
            static function (array $a, array $b): int {
                $aTs = strtotime((string) ($a['timestamp'] ?? '')) ?: 0;
                $bTs = strtotime((string) ($b['timestamp'] ?? '')) ?: 0;
                return $aTs <=> $bTs;
            }
        );
        if ($limit > 0 && count($artifacts) > $limit) {
            $artifacts = array_slice($artifacts, -$limit);
        }
        return $artifacts;
    }

    public function createModelProposal(
        string $sourceRunId,
        string $baseModelId,
        array $proposal,
        array $llmMetadata = []
    ): array {
        $now = $this->nowIso();
        $entry = [
            'proposal_id' => 'prop_' . substr(bin2hex(random_bytes(8)), 0, 12),
            'status' => 'draft',
            'source_run_id' => $sourceRunId,
            'base_model_id' => $baseModelId,
            'proposal' => $proposal,
            'llm_metadata' => $llmMetadata,
            'created_at' => $now,
            'updated_at' => $now,
        ];
        $this->store->appendModelProposal($entry);
        return $entry;
    }

    public function listModelProposals(int $limit = 100): array
    {
        $state = $this->store->readAll();
        $proposals = array_values(is_array($state['model_proposals'] ?? null) ? $state['model_proposals'] : []);
        usort(
            $proposals,
            static function (array $a, array $b): int {
                $aTs = strtotime((string) ($a['updated_at'] ?? '')) ?: 0;
                $bTs = strtotime((string) ($b['updated_at'] ?? '')) ?: 0;
                return $bTs <=> $aTs;
            }
        );
        if ($limit > 0 && count($proposals) > $limit) {
            $proposals = array_slice($proposals, 0, $limit);
        }
        return $proposals;
    }

    public function getModelProposal(string $proposalId): array
    {
        $state = $this->store->readAll();
        $proposals = array_values(is_array($state['model_proposals'] ?? null) ? $state['model_proposals'] : []);
        foreach ($proposals as $proposal) {
            if ((string) ($proposal['proposal_id'] ?? '') === $proposalId) {
                return $proposal;
            }
        }
        throw new RuntimeException('proposal not found');
    }

    public function updateModelProposalStatus(string $proposalId, string $status, array $metadataUpdates = []): array
    {
        $this->assertProposalStatus($status);
        $proposal = $this->getModelProposal($proposalId);
        $proposal['status'] = $status;
        $proposal['updated_at'] = $this->nowIso();
        if (!empty($metadataUpdates)) {
            $currentMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
            $proposal['llm_metadata'] = array_merge($currentMetadata, $metadataUpdates);
        }
        $this->store->replaceModelProposal($proposalId, $proposal);
        return $proposal;
    }

    public function enqueueModelProposalPhase0(string $proposalId): array
    {
        $proposal = $this->getModelProposal($proposalId);
        $proposal['status'] = 'queued_phase0';
        $proposal['updated_at'] = $this->nowIso();
        $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
        $llmMetadata['phase0_requested_at'] = $proposal['updated_at'];
        $proposal['llm_metadata'] = $llmMetadata;
        $this->store->replaceModelProposal($proposalId, $proposal);
        return $proposal;
    }

    public function processQueuedModelProposalsPhase0(int $limit = 20): array
    {
        if ($limit <= 0) {
            $limit = 20;
        }
        $proposals = $this->listModelProposals(1000);
        $processed = [];
        foreach ($proposals as $proposal) {
            if ((string) ($proposal['status'] ?? '') !== 'queued_phase0') {
                continue;
            }
            if (count($processed) >= $limit) {
                break;
            }
            $proposalId = (string) ($proposal['proposal_id'] ?? '');
            if ($proposalId === '') {
                continue;
            }
            $validated = $this->autoValidateProposalForPhase0($proposal);
            $validated['updated_at'] = $this->nowIso();
            $this->store->replaceModelProposal($proposalId, $validated);
            $processed[] = [
                'proposal_id' => $proposalId,
                'status' => (string) ($validated['status'] ?? ''),
            ];
        }
        return [
            'processed_count' => count($processed),
            'processed' => $processed,
        ];
    }

    public function evaluateModelProposalsKpis(float $lossThreshold = 0.5): array
    {
        $state = $this->store->readAll();
        $proposals = $this->listModelProposals(1000);
        $metrics = is_array($state['metrics'] ?? null) ? $state['metrics'] : [];
        $metricsByModel = [];
        foreach ($metrics as $metric) {
            $metricsByModel[(string) ($metric['model_id'] ?? '')] = $metric['metrics'] ?? [];
        }

        $evaluated = [];
        foreach ($proposals as $proposal) {
            if ((string) ($proposal['status'] ?? '') !== 'validated_phase0') {
                continue;
            }
            $proposalId = (string) ($proposal['proposal_id'] ?? '');
            if ($proposalId === '') {
                continue;
            }
            $modelMetrics = $metricsByModel[$proposalId] ?? null;
            if ($modelMetrics === null) {
                continue; // Wait for metrics
            }
            $valLoss = (float) ($modelMetrics['val_loss_total'] ?? 999.0);
            
            $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
            $llmMetadata['kpi_evaluation'] = [
                'val_loss_total' => $valLoss,
                'threshold' => $lossThreshold,
                'evaluated_at' => $this->nowIso(),
            ];
            
            if ($valLoss <= $lossThreshold) {
                $proposal['status'] = 'accepted';
                $llmMetadata['kpi_result'] = 'promoted';
            } else {
                $proposal['status'] = 'rejected';
                $llmMetadata['kpi_result'] = 'rejected_by_loss';
            }
            
            $proposal['llm_metadata'] = $llmMetadata;
            $proposal['updated_at'] = $this->nowIso();
            $this->store->replaceModelProposal($proposalId, $proposal);
            
            $evaluated[] = [
                'proposal_id' => $proposalId,
                'status' => $proposal['status'],
                'val_loss_total' => $valLoss,
            ];
        }

        return [
            'evaluated_count' => count($evaluated),
            'evaluated' => $evaluated,
        ];
    }

    public function markStaleRunsRetrying(int $staleAfterSeconds): array
    {
        if ($staleAfterSeconds < 0) {
            throw new RuntimeException('invalid stale_after_seconds');
        }
        $state = $this->store->readAll();
        $runs = is_array($state['runs'] ?? null) ? $state['runs'] : [];
        $now = time();
        $updatedRunIds = [];
        foreach ($runs as $runId => $run) {
            $status = (string) ($run['status'] ?? '');
            if (!in_array($status, ['queued', 'running'], true)) {
                continue;
            }
            $lastSignal = (string) ($run['heartbeat_at'] ?? $run['updated_at'] ?? '');
            $lastSignalTs = strtotime($lastSignal);
            if ($lastSignalTs === false) {
                continue;
            }
            if (($now - $lastSignalTs) < $staleAfterSeconds) {
                continue;
            }
            $run['status'] = 'retrying';
            $run['updated_at'] = $this->nowIso();
            $this->store->upsertRun($run);
            $this->store->appendEvent([
                'run_id' => $runId,
                'event_type' => 'watchdog_retry',
                'label' => 'Run marcat com retrying per timeout de heartbeat',
                'level' => 'warning',
                'timestamp' => $this->nowIso(),
                'details' => [
                    'stale_after_seconds' => $staleAfterSeconds,
                    'last_signal_at' => $lastSignal,
                ],
            ]);
            $updatedRunIds[] = $runId;
        }
        return [
            'stale_after_seconds' => $staleAfterSeconds,
            'updated_runs' => $updatedRunIds,
            'updated_count' => count($updatedRunIds),
        ];
    }

    public function resetAllData(bool $preserveBestModels = false, int $preserveLimit = 3): array
    {
        if (!method_exists($this->store, 'resetAll')) {
            throw new RuntimeException('reset not supported');
        }
        $before = $this->store->readAll();
        $counts = [
            'runs' => count(is_array($before['runs'] ?? null) ? $before['runs'] : []),
            'events' => count(is_array($before['events'] ?? null) ? $before['events'] : []),
            'metrics' => count(is_array($before['metrics'] ?? null) ? $before['metrics'] : []),
            'artifacts' => count(is_array($before['artifacts'] ?? null) ? $before['artifacts'] : []),
            'model_proposals' => count(is_array($before['model_proposals'] ?? null) ? $before['model_proposals'] : []),
            'execution_requests' => count(is_array($before['execution_requests'] ?? null) ? $before['execution_requests'] : []),
        ];
        $preserved = [
            'runs' => 0,
            'events' => 0,
            'metrics' => 0,
            'artifacts' => 0,
            'model_proposals' => 0,
            'execution_requests' => 0,
            'artifact_files' => 0,
            'proposal_ids' => [],
        ];
        if ($preserveBestModels) {
            if (!method_exists($this->store, 'replaceAll')) {
                throw new RuntimeException('selective reset not supported');
            }
            $preservedState = $this->buildPreservedBestState($before, max(1, $preserveLimit));
            $preserved = $preservedState['summary'];
            $deletedArtifactFiles = $this->deleteDirectoryContentsExcept($this->artifactStorageDir(), $preservedState['artifact_file_paths']);
            $this->store->replaceAll($preservedState['state']);
        } else {
            $deletedArtifactFiles = $this->deleteDirectoryContents($this->artifactStorageDir());
            $this->store->resetAll();
        }
        return [
            'ok' => true,
            'deleted' => array_merge($counts, ['artifact_files' => $deletedArtifactFiles]),
            'preserved' => $preserved,
            'preserve_best_models' => $preserveBestModels,
            'reset_at' => $this->nowIso(),
        ];
    }

    private function assertStatus(string $status): void
    {
        if (!in_array($status, self::VALID_STATUSES, true)) {
            throw new RuntimeException('invalid status');
        }
    }

    private function assertProposalStatus(string $status): void
    {
        if (!in_array($status, self::VALID_PROPOSAL_STATUSES, true)) {
            throw new RuntimeException('invalid proposal status');
        }
    }

    public function lockAcceptedProposalForTraining(string $trainerId): array|null
    {
        $state = $this->store->readAll();
        $proposals = is_array($state['model_proposals'] ?? null) ? $state['model_proposals'] : [];
        $candidates = array_filter(
            $proposals,
            static function (array $proposal): bool {
                return ((string) ($proposal['status'] ?? '')) === 'accepted';
            }
        );

        if (count($candidates) === 0) {
            return null; // Cap a punt d'entrenar
        }

        // Ordenar del més antic que està accepted
        usort(
            $candidates,
            static function (array $a, array $b): int {
                $aTs = strtotime((string) ($a['updated_at'] ?? '')) ?: 0;
                $bTs = strtotime((string) ($b['updated_at'] ?? '')) ?: 0;
                return $aTs <=> $bTs;
            }
        );

        $selected = $candidates[0];
        $selected['status'] = 'training';
        $selected['updated_at'] = $this->nowIso();
        
        $llmMetadata = is_array($selected['llm_metadata'] ?? null) ? $selected['llm_metadata'] : [];
        $llmMetadata['training_locked_by'] = $trainerId;
        $llmMetadata['training_started_at'] = $selected['updated_at'];
        $selected['llm_metadata'] = $llmMetadata;

        $this->store->replaceModelProposal((string) ($selected['proposal_id'] ?? ''), $selected);
        return $selected;
    }

    public function updateProposalStatus(string $proposalId, string $status, array $metadataUpdates = []): array
    {
        if (!in_array($status, self::VALID_PROPOSAL_STATUSES, true)) {
            throw new InvalidArgumentException("Invalid proposal status: {$status}");
        }

        $state = $this->store->readAll();
        $proposals = is_array($state['model_proposals'] ?? null) ? $state['model_proposals'] : [];
        $found = null;
        foreach ($proposals as $proposal) {
            if ((string) ($proposal['proposal_id'] ?? '') === $proposalId) {
                $found = $proposal;
                break;
            }
        }
        
        if ($found === null) {
            throw new RuntimeException("Proposal not found: {$proposalId}");
        }
        
        $found['status'] = $status;
        $found['updated_at'] = $this->nowIso();
        
        if (!empty($metadataUpdates)) {
            $currentMetadata = is_array($found['llm_metadata'] ?? null) ? $found['llm_metadata'] : [];
            $found['llm_metadata'] = array_merge($currentMetadata, $metadataUpdates);
        }
        
        $this->store->replaceModelProposal($proposalId, $found);
        return $found;
    }

    private function autoValidateProposalForPhase0(array $proposal): array
    {
        $sourceRunId = (string) ($proposal['source_run_id'] ?? '');
        $baseModelId = (string) ($proposal['base_model_id'] ?? '');
        $candidate = $proposal['proposal'] ?? [];
        $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
        $phase0Errors = $this->validateProposalStructureForPhase0($proposal);
        $validationOk = $sourceRunId !== '' && $baseModelId !== '' && is_array($candidate) && count($candidate) > 0 && count($phase0Errors) === 0;
        $llmMetadata['phase0_auto'] = [
            'mode' => 'api-structural-check',
            'ok' => $validationOk,
            'checked_at' => $this->nowIso(),
            'errors' => $phase0Errors,
        ];
        if ($validationOk) {
            $proposal['status'] = 'validated_phase0';
            $llmMetadata['phase0_validated_at'] = $this->nowIso();
        } else {
            $proposal['status'] = 'rejected';
            $llmMetadata['phase0_rejected_reason'] = count($phase0Errors) > 0 ? implode(' | ', $phase0Errors) : 'invalid proposal payload for phase0 queue';
        }
        $proposal['llm_metadata'] = $llmMetadata;
        return $proposal;
    }

    private function validateProposalStructureForPhase0(array $proposal): array
    {
        $candidate = $proposal['proposal'] ?? null;
        if (!is_array($candidate)) {
            return ['proposal payload missing'];
        }
        $modelDefinition = $candidate['model_definition'] ?? null;
        if (!is_array($modelDefinition)) {
            return ['model_definition missing'];
        }
        $architecture = $modelDefinition['architecture_definition'] ?? null;
        if (!is_array($architecture)) {
            return ['architecture_definition missing'];
        }

        $errors = [];
        $usedInputs = $architecture['used_inputs'] ?? null;
        if (!is_array($usedInputs) || count($usedInputs) === 0) {
            $errors[] = 'used_inputs missing or empty';
        }
        foreach ((array) ($architecture['branches'] ?? []) as $branchIndex => $branch) {
            if (!is_array($branch)) {
                $errors[] = "branch[$branchIndex] invalid";
                continue;
            }
            if (trim((string) ($branch['input_source_layer'] ?? '')) === '') {
                $errors[] = "branch[$branchIndex].input_source_layer missing";
            }
            if (trim((string) ($branch['output_feature_map_name'] ?? '')) === '') {
                $errors[] = "branch[$branchIndex].output_feature_map_name missing";
            }
        }
        foreach ((array) ($architecture['merges'] ?? []) as $mergeIndex => $merge) {
            if (!is_array($merge)) {
                $errors[] = "merge[$mergeIndex] invalid";
                continue;
            }
            $sourceMaps = $merge['source_feature_maps'] ?? null;
            if (!is_array($sourceMaps) || count($sourceMaps) === 0) {
                $errors[] = "merge[$mergeIndex].source_feature_maps missing or empty";
            }
            if (trim((string) ($merge['output_feature_map_name'] ?? '')) === '') {
                $errors[] = "merge[$mergeIndex].output_feature_map_name missing";
            }
        }
        foreach ((array) ($architecture['output_heads'] ?? []) as $headIndex => $head) {
            if (!is_array($head)) {
                $errors[] = "output_head[$headIndex] invalid";
                continue;
            }
            if (trim((string) ($head['source_feature_map'] ?? '')) === '') {
                $errors[] = "output_head[$headIndex].source_feature_map missing";
            }
            if (trim((string) ($head['output_layer_name'] ?? '')) === '') {
                $errors[] = "output_head[$headIndex].output_layer_name missing";
            }
        }
        return $errors;
    }

    private function nowIso(): string
    {
        return gmdate('c');
    }

    private function policyConfigForProfile(string $profile): array
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
            $base['weights'] = ['loss' => 0.50, 'time' => 0.20, 'stability' => 0.20, 'quality' => 0.10];
            $base['loss_cap'] = 300000.0;
            $base['time_cap_seconds'] = 900.0;
            $base['hard_time_limit_seconds'] = 1800.0;
            $base['champion_min_score'] = 35.0;
            $base['champion_margin_min'] = 1.0;
        } elseif (in_array($selected, ['real', 'large', 'real_large', 'prod'], true)) {
            $base['profile'] = 'real_large';
            $base['weights'] = ['loss' => 0.65, 'time' => 0.05, 'stability' => 0.20, 'quality' => 0.10];
            $base['time_cap_seconds'] = 7200.0;
            $base['hard_time_limit_seconds'] = 14400.0;
            $base['champion_min_score'] = 50.0;
            $base['champion_margin_min'] = 3.0;
        }
        return $base;
    }

    private function evaluateProposalSelection(array $proposal, array $policy): array
    {
        $status = (string) ($proposal['status'] ?? '');
        $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
        $trainingKpis = is_array($llmMetadata['training_kpis'] ?? null) ? $llmMetadata['training_kpis'] : [];
        $kpiEval = is_array($llmMetadata['kpi_evaluation'] ?? null) ? $llmMetadata['kpi_evaluation'] : [];
        $kpiResult = (string) ($llmMetadata['kpi_result'] ?? '');
        $valLoss = isset($trainingKpis['val_loss_total']) ? (float) $trainingKpis['val_loss_total'] : (isset($kpiEval['val_loss_total']) ? (float) $kpiEval['val_loss_total'] : null);
        $trainingTime = isset($trainingKpis['training_time_seconds']) ? (float) $trainingKpis['training_time_seconds'] : (isset($llmMetadata['training_time']) ? (float) $llmMetadata['training_time'] : null);
        $constraintsFailed = [];
        if (!in_array($status, ['trained', 'accepted', 'validated_phase0'], true)) {
            $constraintsFailed[] = 'status_not_allowed';
        }
        if ($valLoss === null) {
            $constraintsFailed[] = 'missing_val_loss_total';
        }
        if ($kpiResult === 'rejected_by_loss') {
            $constraintsFailed[] = 'kpi_rejected';
        }
        $weights = is_array($policy['weights'] ?? null) ? $policy['weights'] : [];
        $normalizedLoss = ($valLoss !== null && (float) $policy['loss_cap'] > 0) ? max(0.0, 1.0 - min($valLoss, (float) $policy['loss_cap']) / (float) $policy['loss_cap']) : 0.0;
        $normalizedTime = ($trainingTime !== null && (float) $policy['time_cap_seconds'] > 0) ? max(0.0, 1.0 - min($trainingTime, (float) $policy['time_cap_seconds']) / (float) $policy['time_cap_seconds']) : 0.5;
        $normalizedStability = $status === 'trained' ? 1.0 : ($status === 'accepted' ? 0.75 : 0.55);
        $normalizedQuality = $kpiResult === 'promoted' ? 1.0 : ($kpiResult === '' ? 0.7 : 0.5);
        $rawScore = 100.0 * (
            ((float) ($weights['loss'] ?? 0.55)) * $normalizedLoss +
            ((float) ($weights['time'] ?? 0.15)) * $normalizedTime +
            ((float) ($weights['stability'] ?? 0.20)) * $normalizedStability +
            ((float) ($weights['quality'] ?? 0.10)) * $normalizedQuality
        );
        $penalties = [];
        if ($trainingTime !== null && $trainingTime > (float) ($policy['hard_time_limit_seconds'] ?? 3600.0)) {
            $penalties[] = ['name' => 'hard_time_limit', 'points' => 15.0];
            $rawScore -= 15.0;
        }
        $eligible = count($constraintsFailed) === 0;
        $selectionReason = !$eligible ? 'ineligible_due_to_constraints' : ($status === 'trained' ? 'eligible_trained_candidate' : 'eligible_pretrained_candidate');
        return [
            'proposal_id' => (string) ($proposal['proposal_id'] ?? ''),
            'source_run_id' => (string) ($proposal['source_run_id'] ?? ''),
            'status' => $status,
            'eligible' => $eligible,
            'score' => max(0.0, round($rawScore, 4)),
            'selection_reason' => $selectionReason,
            'constraints_failed' => $constraintsFailed,
            'score_breakdown' => [
                'normalized' => ['loss' => round($normalizedLoss, 6), 'time' => round($normalizedTime, 6), 'stability' => round($normalizedStability, 6), 'quality' => round($normalizedQuality, 6)],
                'penalties' => $penalties,
                'metrics_used' => ['val_loss_total' => $valLoss, 'training_time_seconds' => $trainingTime, 'kpi_result' => $kpiResult],
            ],
        ];
    }

    private function buildChampionPayload(array $proposals, string $scope, ?string $runId, array $policy, int $topN): array
    {
        $evaluated = [];
        foreach ($proposals as $proposal) {
            $decision = $this->evaluateProposalSelection($proposal, $policy);
            if ((bool) ($decision['eligible'] ?? false)) {
                $evaluated[] = ['proposal' => $proposal, 'decision' => $decision];
            }
        }
        usort($evaluated, static function (array $a, array $b): int {
            return ((float) ($b['decision']['score'] ?? 0.0)) <=> ((float) ($a['decision']['score'] ?? 0.0));
        });
        $active = null;
        foreach ($proposals as $proposal) {
            $metadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
            if (($metadata['champion_active'] ?? false) !== true) {
                continue;
            }
            if ((string) ($metadata['champion_scope'] ?? '') !== $scope) {
                continue;
            }
            $active = $proposal;
            break;
        }
        $champion = null;
        if ($active !== null) {
            foreach ($evaluated as $entry) {
                if ((string) ($entry['proposal']['proposal_id'] ?? '') === (string) ($active['proposal_id'] ?? '')) {
                    $champion = $entry;
                    break;
                }
            }
        }
        if ($champion === null && count($evaluated) > 0) {
            $champion = $evaluated[0];
        }
        if (is_array($champion)) {
            $champion = $this->applyPersistedChampionDecision($champion, $scope);
        }
        return [
            'scope' => $scope,
            'run_id' => $runId,
            'policy_version' => (string) ($policy['policy_version'] ?? 'selection_policy_v1_1'),
            'policy_profile' => (string) ($policy['profile'] ?? 'default'),
            'champion' => $champion,
            'top_candidates' => $this->attachCandidateDeltas(array_slice($evaluated, 0, max(1, $topN))),
        ];
    }

    private function attachCandidateDeltas(array $entries): array
    {
        $previousScore = null;
        foreach ($entries as $index => $entry) {
            if (!is_array($entry)) {
                continue;
            }
            $decision = is_array($entry['decision'] ?? null) ? $entry['decision'] : [];
            $score = isset($decision['score']) ? (float) $decision['score'] : null;
            $delta = null;
            if ($index > 0 && $previousScore !== null && $score !== null) {
                $delta = round($previousScore - $score, 4);
            }
            $entry['delta_from_previous'] = $delta;
            $entry['primary_factors'] = $this->buildPrimaryFactors($decision);
            $entries[$index] = $entry;
            if ($score !== null) {
                $previousScore = $score;
            }
        }
        return $entries;
    }

    private function buildPrimaryFactors(array $decision): array
    {
        $normalized = is_array(($decision['score_breakdown'] ?? [])['normalized'] ?? null) ? ($decision['score_breakdown']['normalized']) : [];
        $pairs = [];
        foreach (['loss', 'time', 'stability', 'quality'] as $key) {
            if (isset($normalized[$key])) {
                $pairs[] = ['name' => $key, 'value' => (float) $normalized[$key]];
            }
        }
        usort($pairs, static fn(array $a, array $b): int => $b['value'] <=> $a['value']);
        return array_slice($pairs, 0, 2);
    }

    private function applyPersistedChampionDecision(array $entry, string $scope): array
    {
        $proposal = is_array($entry['proposal'] ?? null) ? $entry['proposal'] : [];
        $decision = is_array($entry['decision'] ?? null) ? $entry['decision'] : [];
        $metadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
        if (($metadata['champion_active'] ?? false) !== true) {
            return $entry;
        }
        if ((string) ($metadata['champion_scope'] ?? '') !== $scope) {
            return $entry;
        }
        if (isset($metadata['champion_score']) && is_numeric($metadata['champion_score'])) {
            $decision['score'] = (float) $metadata['champion_score'];
        }
        if (isset($metadata['champion_selection_reason']) && is_string($metadata['champion_selection_reason'])) {
            $decision['selection_reason'] = (string) $metadata['champion_selection_reason'];
        }
        if (isset($metadata['champion_score_breakdown']) && is_array($metadata['champion_score_breakdown'])) {
            $decision['score_breakdown'] = $metadata['champion_score_breakdown'];
        }
        $entry['decision'] = $decision;
        $entry['primary_factors'] = $this->buildPrimaryFactors($decision);
        return $entry;
    }

    private function inferReferenceRole(array $reference, int $index, int $total): string
    {
        $reason = (string) ($reference['selection_reason'] ?? '');
        if ($reason === 'local_fallback') {
            return 'fallback';
        }
        if ($index === 0) {
            return 'top';
        }
        if ($index === $total - 1 && $total > 2) {
            return 'exploration';
        }
        return 'reference';
    }

    private function buildRunSummaryText(array $proposalsByStatus, $champion, int $artifactCount): string
    {
        $generated = array_sum($proposalsByStatus);
        $trained = (int) ($proposalsByStatus['trained'] ?? 0);
        $championId = '';
        if (is_array($champion)) {
            $championProposal = is_array($champion['proposal'] ?? null) ? $champion['proposal'] : [];
            $championId = (string) ($championProposal['proposal_id'] ?? '');
        }
        $parts = ["generated {$generated}", "trained {$trained}", "artifacts {$artifactCount}"];
        if ($championId !== '') {
            $parts[] = "champion {$championId}";
        }
        return implode(' · ', $parts);
    }

    private function buildShortRationale(array $decision, array $trainingKpis): string
    {
        $score = isset($decision['score']) ? (float) $decision['score'] : 0.0;
        $valLoss = isset($trainingKpis['val_loss_total']) ? (float) $trainingKpis['val_loss_total'] : null;
        $time = isset($trainingKpis['training_time_seconds']) ? (float) $trainingKpis['training_time_seconds'] : null;
        $parts = [sprintf('score %.2f', $score)];
        if ($valLoss !== null) {
            $parts[] = 'val_loss ' . number_format($valLoss, 2, '.', '');
        }
        if ($time !== null) {
            $parts[] = 'time ' . number_format($time, 2, '.', '') . 's';
        }
        return implode(' · ', $parts);
    }

    private function updateExecutionRequestStatus(
        string $requestId,
        string $status,
        ?string $workerId = null,
        array $resultSummary = [],
        array $resultArtifacts = [],
        ?string $errorSummary = null
    ): array {
        if (!in_array($status, self::VALID_EXECUTION_REQUEST_STATUSES, true)) {
            throw new InvalidArgumentException('invalid execution request status');
        }
        $request = $this->getExecutionRequest($requestId);
        $request['status'] = $status;
        $request['updated_at'] = $this->nowIso();
        if ($workerId !== null) {
            $request['claimed_by_worker'] = $workerId;
        }
        if (in_array($status, ['claimed', 'running'], true)) {
            $request['heartbeat_at'] = $this->nowIso();
        }
        if (!empty($resultSummary)) {
            $currentSummary = is_array($request['result_summary'] ?? null) ? $request['result_summary'] : [];
            $request['result_summary'] = array_merge($currentSummary, $resultSummary);
        }
        if (!empty($resultArtifacts)) {
            $request['result_artifacts'] = $resultArtifacts;
        }
        if ($errorSummary !== null) {
            $request['error_summary'] = $errorSummary;
        }
        $this->store->replaceExecutionRequest($requestId, $request);
        return $this->normalizeExecutionRequestView($request);
    }

    private function normalizeExecutionRequestConfig(string $type, array $config): array
    {
        return [
            'profile' => (string) ($config['profile'] ?? 'small_test'),
            'generations' => max(1, (int) ($config['generations'] ?? 1)),
            'models_per_generation' => max(1, (int) ($config['models_per_generation'] ?? 1)),
            'max_epochs' => max(0, (int) ($config['max_epochs'] ?? 0)),
            'max_training_seconds' => max(0, (int) ($config['max_training_seconds'] ?? 0)),
            'champion_scope' => (string) ($config['champion_scope'] ?? 'run'),
            'auto_feed' => (bool) ($config['auto_feed'] ?? false),
            'resume_enabled' => (bool) ($config['resume_enabled'] ?? true),
            'bootstrap_seed_model_if_empty' => (bool) ($config['bootstrap_seed_model_if_empty'] ?? false),
            'auto_process_proposals_phase0' => (bool) ($config['auto_process_proposals_phase0'] ?? true),
            'llm_min_interval_seconds' => max(0, (int) ($config['llm_min_interval_seconds'] ?? 30)),
            'execution_mode' => (string) ($config['execution_mode'] ?? 'once'),
            'dataset_mode' => (string) ($config['dataset_mode'] ?? 'small_subset'),
            'type_description' => $this->executionTypeDescription($type),
        ];
    }

    private function executionTypeDescription(string $type): string
    {
        return match ($type) {
            'smoke_run' => 'Execució ràpida per validar el pipeline complet amb cost baix.',
            'micro_training' => 'Run curt amb training real per revisar loop i artifacts.',
            'integration_matrix' => 'Bateria de runs curts per validar estabilitat del sistema.',
            'resume_training' => 'Reprèn o reinicia entrenaments pendents segons checkpoints.',
            'cleanup' => 'Neteja i estabilitza estats inconsistents sense entrenar models nous.',
            default => 'Execució personalitzada.',
        };
    }

    private function normalizeExecutionRequestView(array $request): array
    {
        $type = (string) ($request['type'] ?? '');
        $config = $this->normalizeExecutionRequestConfig($type, is_array($request['config'] ?? null) ? $request['config'] : []);
        $resultSummary = is_array($request['result_summary'] ?? null) ? $request['result_summary'] : [];
        $runIds = [];
        foreach ((array) ($resultSummary['run_ids'] ?? []) as $runId) {
            if (is_string($runId) && trim($runId) !== '') {
                $runIds[] = trim($runId);
            }
        }
        $currentRunId = (string) ($resultSummary['current_run_id'] ?? $resultSummary['run_id'] ?? '');
        if ($currentRunId !== '' && !in_array($currentRunId, $runIds, true)) {
            $runIds[] = $currentRunId;
        }
        $claimedAt = strtotime((string) ($request['claimed_at'] ?? '')) ?: 0;
        $updatedAt = strtotime((string) ($request['updated_at'] ?? '')) ?: 0;
        $elapsedSeconds = null;
        if ($claimedAt > 0 && $updatedAt > 0 && $updatedAt >= $claimedAt) {
            $elapsedSeconds = $updatedAt - $claimedAt;
        }
        $generationsCompleted = (int) ($resultSummary['generations_completed'] ?? ($resultSummary['generations'] ?? 0));
        $generationsTotal = (int) ($config['generations'] ?? 1);
        $modelsGenerated = (int) ($resultSummary['models_generated'] ?? ($resultSummary['proposals_created'] ?? 0));
        $modelsTrained = (int) ($resultSummary['models_trained'] ?? ($resultSummary['trained_total'] ?? ($resultSummary['proposals_validated_phase0'] ?? 0)));
        $progressPercent = 0.0;
        if ($generationsTotal > 0) {
            $progressPercent = min(100.0, round((($generationsCompleted + ($modelsGenerated > $modelsTrained ? 0.35 : 0.0)) / $generationsTotal) * 100.0, 1));
        }
        $requestStatus = (string) ($request['status'] ?? '');
        $currentStage = (string) ($resultSummary['stage'] ?? '');
        $currentStageLabel = (string) ($resultSummary['stage_label'] ?? '');
        if (in_array($requestStatus, ['completed', 'failed', 'cancelled'], true)) {
            $currentStage = $requestStatus;
            $currentStageLabel = $this->executionFinalStatusLabel($requestStatus);
        }
        return array_merge($request, [
            'config' => $config,
            'type_description' => $this->executionTypeDescription($type),
            'progress' => [
                'generations_completed' => $generationsCompleted,
                'generations_total' => $generationsTotal,
                'models_generated' => $modelsGenerated,
                'models_trained' => $modelsTrained,
                'progress_percent' => $progressPercent,
            ],
            'current_stage' => $currentStage,
            'current_stage_label' => $currentStageLabel,
            'current_run_id' => $currentRunId,
            'run_ids' => $runIds,
            'started_at' => (string) ($request['claimed_at'] ?? ''),
            'completed_at' => in_array((string) ($request['status'] ?? ''), ['completed', 'failed', 'cancelled'], true) ? (string) ($request['updated_at'] ?? '') : '',
            'elapsed_seconds' => $elapsedSeconds,
        ]);
    }

    private function getRawExecutionRequest(string $requestId): array
    {
        $state = $this->store->readAll();
        $requests = array_values(is_array($state['execution_requests'] ?? null) ? $state['execution_requests'] : []);
        foreach ($requests as $request) {
            if ((string) ($request['request_id'] ?? '') === $requestId) {
                return $request;
            }
        }
        throw new RuntimeException('execution_request not found');
    }

    private function buildExecutionLifecycle(array $request): array
    {
        $steps = [
            [
                'status' => 'pending',
                'timestamp' => (string) ($request['created_at'] ?? ''),
                'label' => 'Execution request creada',
                'completed' => ((string) ($request['created_at'] ?? '')) !== '',
            ],
            [
                'status' => 'claimed',
                'timestamp' => (string) ($request['claimed_at'] ?? ''),
                'label' => 'Worker ha reclamat l\'execuci\u00f3',
                'completed' => ((string) ($request['claimed_at'] ?? '')) !== '',
            ],
            [
                'status' => 'running',
                'timestamp' => (string) ($request['started_at'] ?? $request['heartbeat_at'] ?? ''),
                'label' => 'Execuci\u00f3 en curs',
                'completed' => in_array((string) ($request['status'] ?? ''), ['running', 'completed', 'failed', 'cancelled'], true),
            ],
            [
                'status' => (string) ($request['status'] ?? ''),
                'timestamp' => (string) ($request['completed_at'] ?? ''),
                'label' => $this->executionFinalStatusLabel((string) ($request['status'] ?? '')),
                'completed' => in_array((string) ($request['status'] ?? ''), ['completed', 'failed', 'cancelled'], true),
            ],
        ];
        return array_values(array_filter($steps, static fn(array $step): bool => (bool) ($step['completed'] ?? false) || (string) ($step['status'] ?? '') === 'running'));
    }

    private function executionFinalStatusLabel(string $status): string
    {
        return match ($status) {
            'completed' => 'Execuci\u00f3 completada',
            'failed' => 'Execuci\u00f3 fallida',
            'cancelled' => 'Execuci\u00f3 cancel\u00b7lada',
            default => 'Execuci\u00f3 en progr\u00e9s',
        };
    }

    private function buildExecutionRunAutopsy(string $runId, int $timelineLimit): array
    {
        $summary = $this->getSummary($runId);
        $timelinePayload = $this->getRunTimeline($runId, $timelineLimit);
        $referencesPayload = $this->getRunReferences($runId, 5);
        $timeline = is_array($timelinePayload['timeline'] ?? null) ? $timelinePayload['timeline'] : [];
        $proposals = array_values(array_filter(
            $this->listModelProposals(1000),
            static fn(array $proposal): bool => (string) ($proposal['source_run_id'] ?? '') === $runId
        ));
        $artifacts = $this->listRunArtifacts($runId, 200);

        return [
            'run_id' => $runId,
            'run' => is_array($summary['run'] ?? null) ? $summary['run'] : [],
            'summary_text' => (string) ($summary['summary_text'] ?? ''),
            'counts' => is_array($summary['counts'] ?? null) ? $summary['counts'] : [],
            'proposals_by_status' => is_array($summary['proposals_by_status'] ?? null) ? $summary['proposals_by_status'] : [],
            'latest_event' => $summary['latest_event'] ?? null,
            'latest_artifact' => $summary['latest_artifact'] ?? null,
            'references' => $referencesPayload,
            'timeline' => $timeline,
            'proposals' => array_map(fn(array $proposal): array => $this->buildExecutionProposalSummary($proposal), $proposals),
            'artifacts' => array_map(fn(array $artifact): array => $this->normalizeArtifactView($artifact), $artifacts),
        ];
    }

    private function buildExecutionProposalSummary(array $proposal): array
    {
        $llmMetadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
        return [
            'proposal_id' => (string) ($proposal['proposal_id'] ?? ''),
            'status' => (string) ($proposal['status'] ?? ''),
            'base_model_id' => (string) ($proposal['base_model_id'] ?? ''),
            'updated_at' => (string) ($proposal['updated_at'] ?? ''),
            'trained_model_uri' => $llmMetadata['trained_model_uri'] ?? null,
            'resumable' => (bool) ($llmMetadata['resumable'] ?? false),
            'last_checkpoint_epoch' => $llmMetadata['last_checkpoint_epoch'] ?? null,
            'training_kpis' => is_array($llmMetadata['training_kpis'] ?? null) ? $llmMetadata['training_kpis'] : [],
            'phase0_auto' => is_array($llmMetadata['phase0_auto'] ?? null) ? $llmMetadata['phase0_auto'] : [],
            'phase0_rejected_reason' => (string) ($llmMetadata['phase0_rejected_reason'] ?? ''),
            'champion_active' => (bool) ($llmMetadata['champion_active'] ?? false),
            'champion_scope' => (string) ($llmMetadata['champion_scope'] ?? ''),
            'repair_depth' => (int) ($llmMetadata['repair_depth'] ?? 0),
            'repaired_from_proposal_id' => (string) ($llmMetadata['repaired_from_proposal_id'] ?? ''),
            'repair_mode' => (string) ($llmMetadata['repair_mode'] ?? ''),
            'repair_attempt' => (int) ($llmMetadata['repair_attempt'] ?? 0),
            'repair_source_error' => (string) ($llmMetadata['repair_source_error'] ?? ''),
        ];
    }

    private function deriveExecutionOutcome(array $request, array $runs, array $resultSummary): array
    {
        $proposalId = (string) ($resultSummary['proposal_id'] ?? '');
        $proposalStatus = (string) ($resultSummary['proposal_status'] ?? '');
        $trainedModelUri = $resultSummary['trained_model_uri'] ?? null;
        $trainingKpiKeys = array_values(array_filter(
            array_map(static fn($key): string => is_string($key) ? $key : '', (array) ($resultSummary['training_kpis_keys'] ?? [])),
            static fn(string $key): bool => $key !== ''
        ));
        $latestEventType = (string) ($resultSummary['latest_event_type'] ?? '');
        $latestArtifactType = (string) ($resultSummary['latest_artifact_type'] ?? '');

        foreach ($runs as $run) {
            $runLatestEvent = is_array($run['latest_event'] ?? null) ? $run['latest_event'] : [];
            $runLatestArtifact = is_array($run['latest_artifact'] ?? null) ? $run['latest_artifact'] : [];
            if ($latestEventType === '') {
                $latestEventType = (string) ($runLatestEvent['event_type'] ?? '');
            }
            if ($latestArtifactType === '') {
                $latestArtifactType = (string) ($runLatestArtifact['artifact_type'] ?? '');
            }
            foreach ((array) ($run['proposals'] ?? []) as $proposal) {
                if (!is_array($proposal)) {
                    continue;
                }
                $candidateKpis = is_array($proposal['training_kpis'] ?? null) ? $proposal['training_kpis'] : [];
                $isPreferred = $proposalId === ''
                    || (bool) ($proposal['champion_active'] ?? false)
                    || (string) ($proposal['status'] ?? '') === 'trained';
                if (!$isPreferred) {
                    continue;
                }
                if ($proposalId === '') {
                    $proposalId = (string) ($proposal['proposal_id'] ?? '');
                }
                if ($proposalStatus === '') {
                    $proposalStatus = (string) ($proposal['status'] ?? '');
                }
                if ($trainedModelUri === null || $trainedModelUri === '') {
                    $trainedModelUri = $proposal['trained_model_uri'] ?? null;
                }
                if (empty($trainingKpiKeys) && !empty($candidateKpis)) {
                    $trainingKpiKeys = array_keys($candidateKpis);
                }
                if ($proposalId !== '' && $proposalStatus !== '' && $trainedModelUri !== null && !empty($trainingKpiKeys)) {
                    break 2;
                }
            }
        }

        return [
            'final_status' => (string) ($request['status'] ?? ''),
            'latest_event_type' => $latestEventType,
            'latest_artifact_type' => $latestArtifactType,
            'champion_decision' => $this->championOutcomeLabel($latestEventType),
            'proposal_id' => $proposalId,
            'proposal_status' => $proposalStatus,
            'trained_model_uri' => $trainedModelUri,
            'training_kpis_keys' => $trainingKpiKeys,
        ];
    }

    private function deriveExecutionReferenceContext(array $request, array $runs, array $resultSummary): array
    {
        $context = is_array($resultSummary['reference_context'] ?? null) ? $resultSummary['reference_context'] : [];
        $references = array_values(array_filter(
            is_array($context['references'] ?? null) ? $context['references'] : [],
            static fn($reference): bool => is_array($reference)
        ));
        if (empty($references) && !empty($runs)) {
            $firstRun = $runs[0];
            $referencesPayload = is_array($firstRun['references'] ?? null) ? $firstRun['references'] : [];
            $references = array_values(array_filter(
                is_array($referencesPayload['references'] ?? null) ? $referencesPayload['references'] : [],
                static fn($reference): bool => is_array($reference)
            ));
            $context = array_merge($referencesPayload, $context);
        }
        $primaryReference = is_array($references[0] ?? null) ? $references[0] : [];
        return [
            'reference_models_count' => (int) ($context['reference_models_count'] ?? count($references)),
            'reference_policy_version' => (string) ($context['reference_policy_version'] ?? ''),
            'fallback_used' => (bool) ($context['fallback_used'] ?? false),
            'primary_reference_proposal_id' => (string) ($primaryReference['proposal_id'] ?? ''),
            'primary_reference_reason' => (string) ($primaryReference['selection_reason'] ?? ''),
            'references' => $references,
        ];
    }

    private function championOutcomeLabel(string $eventType): string
    {
        return match ($eventType) {
            'champion_selected' => 'champion_selected',
            'champion_kept' => 'champion_kept',
            'champion_selection_skipped' => 'champion_selection_skipped',
            default => $eventType,
        };
    }

    private function buildExecutionLogExcerpt(string $outputTail, int $maxLines = 12): array
    {
        if (trim($outputTail) === '') {
            return [
                'line_count' => 0,
                'tail_lines' => [],
                'interesting_lines' => [],
            ];
        }
        $lines = preg_split('/\r\n|\r|\n/', trim($outputTail)) ?: [];
        $filteredLines = array_values(array_filter(
            $lines,
            static function (string $line): bool {
                $normalized = strtolower($line);
                return !str_contains($normalized, 'cuda')
                    && !str_contains($normalized, 'tensorflow/core/platform/cpu_feature_guard')
                    && !str_contains($normalized, 'computation_placer')
                    && !str_contains($normalized, 'could not find cuda drivers')
                    && !str_contains($normalized, 'attempting to register factory')
                    && !str_contains($normalized, '"progress_event": true');
            }
        ));
        $tailLines = array_slice($filteredLines, -$maxLines);
        $interestingLines = array_values(array_filter(
            $filteredLines,
            static function (string $line): bool {
                $normalized = strtolower($line);
                return str_contains($normalized, 'error')
                    || str_contains($normalized, 'fail')
                    || str_contains($normalized, 'traceback')
                    || str_contains($normalized, 'run_id=')
                    || str_contains($normalized, 'trainer')
                    || str_contains($normalized, 'checkpoint')
                    || str_contains($normalized, 'proposal')
                    || str_contains($normalized, 'completed');
            }
        ));

        return [
            'line_count' => count($filteredLines),
            'tail_lines' => array_values($tailLines),
            'interesting_lines' => array_values(array_slice($interestingLines, -12)),
        ];
    }

    private function normalizeArtifactView(array $artifact): array
    {
        $metadata = is_array($artifact['metadata'] ?? null) ? $artifact['metadata'] : [];
        $storageBackend = (string) ($metadata['storage_backend'] ?? ($artifact['storage'] ?? 'unknown'));
        $artifactUri = (string) ($artifact['uri'] ?? '');
        $availability = (string) ($metadata['availability_status'] ?? 'unknown');
        if ($storageBackend === 'server') {
            if ($artifactUri !== '' && is_file($artifactUri)) {
                $availability = 'available';
            } elseif ((string) ($metadata['download_url'] ?? '') !== '') {
                $availability = $availability !== 'unknown' ? $availability : 'available';
            } else {
                $availability = 'missing';
            }
        }
        return [
            'artifact_id' => (string) ($metadata['artifact_id'] ?? ''),
            'artifact_type' => (string) ($artifact['artifact_type'] ?? ''),
            'storage_backend' => $storageBackend,
            'artifact_uri' => $artifactUri,
            'download_url' => (string) ($metadata['download_url'] ?? ''),
            'availability_status' => $availability,
            'checksum' => $artifact['checksum'] ?? null,
            'timestamp' => (string) ($artifact['timestamp'] ?? ''),
            'metadata' => $metadata,
        ];
    }

    private function artifactStorageDir(): string
    {
        $configured = getenv('V2_SERVER_ARTIFACTS_DIR');
        if (is_string($configured) && trim($configured) !== '') {
            return trim($configured);
        }
        return dirname(__DIR__) . '/../storage/artifacts';
    }

    private function buildPreservedBestState(array $state, int $limit): array
    {
        $policy = $this->policyConfigForProfile(getenv('V2_SELECTION_POLICY_PROFILE') ?: 'default');
        $proposals = array_values(array_filter(
            is_array($state['model_proposals'] ?? null) ? $state['model_proposals'] : [],
            static fn(array $proposal): bool => (string) ($proposal['status'] ?? '') === 'trained'
        ));
        $evaluated = [];
        foreach ($proposals as $proposal) {
            $decision = $this->evaluateProposalSelection($proposal, $policy);
            if ((bool) ($decision['eligible'] ?? false)) {
                $evaluated[] = ['proposal' => $proposal, 'decision' => $decision];
            }
        }
        usort($evaluated, static fn(array $a, array $b): int => ((float) ($b['decision']['score'] ?? 0.0)) <=> ((float) ($a['decision']['score'] ?? 0.0)));
        $selectedProposals = [];
        foreach (array_slice($evaluated, 0, max(1, $limit)) as $entry) {
            $proposal = is_array($entry['proposal'] ?? null) ? $entry['proposal'] : [];
            if (!empty($proposal)) {
                $selectedProposals[(string) ($proposal['proposal_id'] ?? '')] = $proposal;
            }
        }
        foreach ($proposals as $proposal) {
            $metadata = is_array($proposal['llm_metadata'] ?? null) ? $proposal['llm_metadata'] : [];
            if (($metadata['champion_active'] ?? false) === true) {
                $selectedProposals[(string) ($proposal['proposal_id'] ?? '')] = $proposal;
            }
        }

        $proposalIds = array_values(array_filter(array_keys($selectedProposals), static fn(string $id): bool => $id !== ''));
        $runIds = [];
        foreach ($selectedProposals as $proposal) {
            $runId = (string) ($proposal['source_run_id'] ?? '');
            if ($runId !== '' && !in_array($runId, $runIds, true)) {
                $runIds[] = $runId;
            }
        }

        $runs = [];
        foreach ((array) ($state['runs'] ?? []) as $runId => $run) {
            if (in_array((string) $runId, $runIds, true) && is_array($run)) {
                $runs[(string) $runId] = $run;
            }
        }
        $events = array_values(array_filter(
            is_array($state['events'] ?? null) ? $state['events'] : [],
            static fn(array $event): bool => in_array((string) ($event['run_id'] ?? ''), $runIds, true)
        ));
        $metrics = array_values(array_filter(
            is_array($state['metrics'] ?? null) ? $state['metrics'] : [],
            static fn(array $metric): bool => in_array((string) ($metric['run_id'] ?? ''), $runIds, true)
        ));
        $artifacts = array_values(array_filter(
            is_array($state['artifacts'] ?? null) ? $state['artifacts'] : [],
            static function (array $artifact) use ($proposalIds, $runIds): bool {
                $metadata = is_array($artifact['metadata'] ?? null) ? $artifact['metadata'] : [];
                $proposalId = (string) ($metadata['proposal_id'] ?? '');
                $artifactType = (string) ($artifact['artifact_type'] ?? '');
                if ($proposalId !== '' && in_array($proposalId, $proposalIds, true) && in_array($artifactType, ['trained_model', 'champion_model', 'checkpoint'], true)) {
                    return true;
                }
                return in_array((string) ($artifact['run_id'] ?? ''), $runIds, true) && $artifactType === 'champion_model';
            }
        ));
        $artifactPaths = [];
        foreach ($artifacts as $artifact) {
            $uri = (string) ($artifact['uri'] ?? '');
            if ($uri !== '' && is_file($uri)) {
                $artifactPaths[] = $uri;
            }
        }

        $preservedState = [
            'runs' => $runs,
            'events' => $events,
            'metrics' => $metrics,
            'artifacts' => $artifacts,
            'model_proposals' => array_values($selectedProposals),
            'execution_requests' => [],
        ];
        return [
            'state' => $preservedState,
            'artifact_file_paths' => $artifactPaths,
            'summary' => [
                'runs' => count($runs),
                'events' => count($events),
                'metrics' => count($metrics),
                'artifacts' => count($artifacts),
                'model_proposals' => count($selectedProposals),
                'execution_requests' => 0,
                'artifact_files' => count($artifactPaths),
                'proposal_ids' => $proposalIds,
            ],
        ];
    }

    private function deltaValue($left, $right): ?float
    {
        if (!is_numeric($left) || !is_numeric($right)) {
            return null;
        }
        return round((float) $left - (float) $right, 4);
    }

    private function winnerLabel($left, $right, bool $higherIsBetter): string
    {
        if (!is_numeric($left) || !is_numeric($right)) {
            return 'unknown';
        }
        $leftValue = (float) $left;
        $rightValue = (float) $right;
        if ($leftValue === $rightValue) {
            return 'tie';
        }
        if ($higherIsBetter) {
            return $leftValue > $rightValue ? 'left' : 'right';
        }
        return $leftValue < $rightValue ? 'left' : 'right';
    }

    private function deleteDirectoryContents(string $directory): int
    {
        if (!is_dir($directory)) {
            return 0;
        }
        $deleted = 0;
        $items = scandir($directory);
        if ($items === false) {
            return 0;
        }
        foreach ($items as $item) {
            if ($item === '.' || $item === '..') {
                continue;
            }
            $path = $directory . DIRECTORY_SEPARATOR . $item;
            if (is_dir($path)) {
                $deleted += $this->deleteDirectoryContents($path);
                if (@rmdir($path)) {
                    $deleted += 1;
                }
                continue;
            }
            if (@unlink($path)) {
                $deleted += 1;
            }
        }
        return $deleted;
    }

    private function deleteDirectoryContentsExcept(string $directory, array $preserveFilePaths): int
    {
        if (!is_dir($directory)) {
            return 0;
        }
        $preserveMap = [];
        foreach ($preserveFilePaths as $path) {
            if (is_string($path) && $path !== '') {
                $real = realpath($path);
                $preserveMap[$real !== false ? $real : $path] = true;
            }
        }
        return $this->deleteDirectoryContentsExceptRecursive($directory, $preserveMap);
    }

    private function deleteDirectoryContentsExceptRecursive(string $directory, array $preserveMap): int
    {
        $deleted = 0;
        $items = scandir($directory);
        if ($items === false) {
            return 0;
        }
        foreach ($items as $item) {
            if ($item === '.' || $item === '..') {
                continue;
            }
            $path = $directory . DIRECTORY_SEPARATOR . $item;
            if (is_dir($path)) {
                $deleted += $this->deleteDirectoryContentsExceptRecursive($path, $preserveMap);
                $remaining = scandir($path);
                if (is_array($remaining) && count($remaining) <= 2 && @rmdir($path)) {
                    $deleted += 1;
                }
                continue;
            }
            $real = realpath($path);
            $normalized = $real !== false ? $real : $path;
            if (isset($preserveMap[$normalized])) {
                continue;
            }
            if (@unlink($path)) {
                $deleted += 1;
            }
        }
        return $deleted;
    }
}
