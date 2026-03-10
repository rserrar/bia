<?php

declare(strict_types=1);

namespace V2ServerApi;

use RuntimeException;

final class ApiService
{
    private const VALID_STATUSES = ['queued', 'running', 'retrying', 'completed', 'failed', 'cancelled'];

    private StateStore $store;

    public function __construct(StateStore $store)
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

    private function assertStatus(string $status): void
    {
        if (!in_array($status, self::VALID_STATUSES, true)) {
            throw new RuntimeException('invalid status');
        }
    }

    private function nowIso(): string
    {
        return gmdate('c');
    }
}

