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
            $this->write($this->emptyState());
        }
    }

    public function readAll(): array
    {
        $handle = fopen($this->filePath, 'c+');
        if ($handle === false) {
            return $this->emptyState();
        }
        flock($handle, LOCK_SH);
        $content = stream_get_contents($handle);
        flock($handle, LOCK_UN);
        fclose($handle);
        if ($content === false || trim($content) === '') {
            return $this->emptyState();
        }
        $decoded = json_decode($content, true);
        return is_array($decoded) ? $decoded : $this->emptyState();
    }

    public function write(array $payload): void
    {
        $handle = fopen($this->filePath, 'c+');
        if ($handle === false) {
            return;
        }
        flock($handle, LOCK_EX);
        ftruncate($handle, 0);
        rewind($handle);
        fwrite($handle, (string) json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
        fflush($handle);
        flock($handle, LOCK_UN);
        fclose($handle);
    }

    public function upsertRun(array $run): void
    {
        $this->mutate(static function (array &$state) use ($run): void {
            $state['runs'][$run['run_id']] = $run;
        });
    }

    public function appendEvent(array $event): void
    {
        $this->mutate(static function (array &$state) use ($event): void {
            $state['events'][] = $event;
        });
    }

    public function appendMetric(array $metric): void
    {
        $this->mutate(static function (array &$state) use ($metric): void {
            $state['metrics'][] = $metric;
        });
    }

    public function appendArtifact(array $artifact): void
    {
        $this->mutate(static function (array &$state) use ($artifact): void {
            $state['artifacts'][] = $artifact;
        });
    }

    private function mutate(callable $callback): void
    {
        $handle = fopen($this->filePath, 'c+');
        if ($handle === false) {
            return;
        }
        flock($handle, LOCK_EX);
        $content = stream_get_contents($handle);
        $state = $this->emptyState();
        if ($content !== false && trim($content) !== '') {
            $decoded = json_decode($content, true);
            if (is_array($decoded)) {
                $state = $decoded;
            }
        }
        $callback($state);
        ftruncate($handle, 0);
        rewind($handle);
        fwrite($handle, (string) json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
        fflush($handle);
        flock($handle, LOCK_UN);
        fclose($handle);
    }

    private function emptyState(): array
    {
        return [
            'runs' => [],
            'events' => [],
            'metrics' => [],
            'artifacts' => [],
        ];
    }
}
