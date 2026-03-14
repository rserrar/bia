<?php

declare(strict_types=1);

namespace V2ServerApi;

interface StateStoreInterface
{
    public function readAll(): array;

    public function upsertRun(array $run): void;

    public function appendEvent(array $event): void;

    public function appendMetric(array $metric): void;

    public function appendArtifact(array $artifact): void;
}
