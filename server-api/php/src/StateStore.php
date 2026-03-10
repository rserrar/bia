<?php

declare(strict_types=1);

namespace V2ServerApi;

final class StateStore
{
    private string $filePath;

    public function __construct(string $filePath)
    {
        $this->filePath = $filePath;
        $dir = dirname($filePath);
        if (!is_dir($dir)) {
            mkdir($dir, 0777, true);
        }
        if (!file_exists($this->filePath)) {
            $this->write([
                'runs' => [],
                'events' => [],
                'metrics' => [],
                'artifacts' => [],
            ]);
        }
    }

    public function readAll(): array
    {
        $content = file_get_contents($this->filePath);
        if ($content === false || $content === '') {
            return [
                'runs' => [],
                'events' => [],
                'metrics' => [],
                'artifacts' => [],
            ];
        }
        $decoded = json_decode($content, true);
        if (!is_array($decoded)) {
            return [
                'runs' => [],
                'events' => [],
                'metrics' => [],
                'artifacts' => [],
            ];
        }
        return $decoded;
    }

    public function write(array $payload): void
    {
        file_put_contents($this->filePath, json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
    }

    public function upsertRun(array $run): void
    {
        $state = $this->readAll();
        $state['runs'][$run['run_id']] = $run;
        $this->write($state);
    }

    public function appendEvent(array $event): void
    {
        $state = $this->readAll();
        $state['events'][] = $event;
        $this->write($state);
    }

    public function appendMetric(array $metric): void
    {
        $state = $this->readAll();
        $state['metrics'][] = $metric;
        $this->write($state);
    }

    public function appendArtifact(array $artifact): void
    {
        $state = $this->readAll();
        $state['artifacts'][] = $artifact;
        $this->write($state);
    }
}

