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

        return [
            'run' => $state['runs'][$runId],
            'counts' => [
                'events' => count($events),
                'metrics' => count($metrics),
                'artifacts' => count($artifacts),
            ],
            'latest_event' => count($events) > 0 ? $events[count($events) - 1] : null,
            'latest_metric' => count($metrics) > 0 ? $metrics[count($metrics) - 1] : null,
            'latest_artifact' => count($artifacts) > 0 ? $artifacts[count($artifacts) - 1] : null,
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

    public function updateModelProposalStatus(string $proposalId, string $status): array
    {
        $this->assertProposalStatus($status);
        $proposal = $this->getModelProposal($proposalId);
        $proposal['status'] = $status;
        $proposal['updated_at'] = $this->nowIso();
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
}
