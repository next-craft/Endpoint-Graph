-- v2-open-issues.md issue 4: UNIQUE(caller_service_id, endpoint_id) collapsed
-- distinct callers (different function/file) in the same service that call the
-- same endpoint into a single overwritten row. Widen the key to include caller
-- identity so each distinct call site gets its own consumer_edges row.
ALTER TABLE public.consumer_edges DROP CONSTRAINT consumer_edges_caller_service_id_endpoint_id_key;
ALTER TABLE public.consumer_edges ADD CONSTRAINT consumer_edges_caller_endpoint_function_key
  UNIQUE (caller_service_id, endpoint_id, caller_file_path, caller_function_name);
