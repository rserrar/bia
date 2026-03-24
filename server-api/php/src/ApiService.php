<?php

declare(strict_types=1);

namespace V2ServerApi;

use RuntimeException;
use InvalidArgumentException;

final class ApiService
{
    private const VALID_STATUSES = ['queued', 'running', 'retrying', 'completed', 'failed', 'cancelled'];
    private const VALID_ARTIFACT_STORAGES = ['drive', 'cloud', 'local'];
    private const VALID_PROPOSAL_STATUSES = ['draft', 'queued_phase0', 'validated_phase0', 'accepted', 'rejected', 'training', 'trained'];

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
            $enriched[] = [
                'proposal_id' => (string) ($proposal['proposal_id'] ?? ''),
                'status' => (string) ($proposal['status'] ?? ''),
                'source_run_id' => (string) ($proposal['source_run_id'] ?? ''),
                'base_model_id' => (string) ($proposal['base_model_id'] ?? ''),
                'updated_at' => (string) ($proposal['updated_at'] ?? ''),
                'trained_model_uri' => $llmMetadata['trained_model_uri'] ?? null,
                'training_kpis' => is_array($llmMetadata['training_kpis'] ?? null) ? $llmMetadata['training_kpis'] : [],
                'prompt_audit' => is_array($llmMetadata['prompt_audit'] ?? null) ? $llmMetadata['prompt_audit'] : [],
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
            ];
        }
        return [
            'policy_version' => $payload['policy_version'] ?? 'selection_policy_v1_1',
            'policy_profile' => $payload['policy_profile'] ?? 'default',
            'shortlist' => $shortlist,
        ];
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

    public function resetAllData(): array
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
        ];
        $this->store->resetAll();
        return [
            'ok' => true,
            'deleted' => $counts,
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
        $validationOk = $sourceRunId !== '' && $baseModelId !== '' && is_array($candidate) && count($candidate) > 0;
        $llmMetadata['phase0_auto'] = [
            'mode' => 'api-structural-check',
            'ok' => $validationOk,
            'checked_at' => $this->nowIso(),
        ];
        if ($validationOk) {
            $proposal['status'] = 'validated_phase0';
            $llmMetadata['phase0_validated_at'] = $this->nowIso();
        } else {
            $proposal['status'] = 'rejected';
            $llmMetadata['phase0_rejected_reason'] = 'invalid proposal payload for phase0 queue';
        }
        $proposal['llm_metadata'] = $llmMetadata;
        return $proposal;
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
}
