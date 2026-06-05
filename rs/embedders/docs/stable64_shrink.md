# stable64_shrink runtime contract

`stable64_shrink` is a runtime primitive for shrinking the logical tail of
stable memory. It is not an allocator and does not delete arbitrary virtual
memory regions.

On success, the call reduces stable memory size, stable memory usage, and
execution memory usage. It releases subnet execution memory, but does not
refund reserved cycles. On failure, stable memory size, accounting, and the
`PageMap` stay unchanged. If the enclosing execution traps or rolls back, the
shrink result is not committed.

`stable64_shrink` is registered as an `ic0` System API import with the same
validation path as the other stable64 functions. There is no separate feature
flag in instrumentation or validation; rollout and compatibility are controlled
by the replica version that accepts this import. Replicas that do not include
this API reject modules importing it as an unknown System API function.

`PageMap::storage_page_limits` makes pages at or above the shrink boundary
invisible, including old checkpoint, base, and overlay pages. Pages written
after a later grow remain visible across subsequent shrink, merge, snapshot,
and reload operations.

Follow-up allocator work should happen above the IC system API. `MemoryManager`
or stable-fs should keep a bucket free list, make `drop_memory(id)` set the
target virtual memory size to zero, return its owned buckets to the free list,
compact live buckets to lower bucket offsets, update metadata, and then call
`stable64_shrink` only for complete free tail buckets. Compaction should be
incremental so it can respect instruction limits.
