-- The views over what `load` built. Run AFTER the dim_ tables and ref_code exist, because the directory
-- counts codes through ref_code.

-- The newest SUCCESSFUL fetch per dataset. A refused or failed fetch can never become current.
CREATE VIEW meta_current_fetch AS
SELECT f.fetch_run_id, f.source_key, f.started_at, f.finished_at, f.release_label, f.value_count, f.is_changed
  FROM meta_fetch_run f
 WHERE f.fetch_run_id = (SELECT max(g.fetch_run_id) FROM meta_fetch_run g
                          WHERE g.source_key = f.source_key AND g.outcome = 'success');

-- Every list we hold today, one row per published item: the table its codes are in, how many codes, the
-- page and release it came from, and when we first saw it. A list printed three times has three rows
-- sharing one list_name. Start here.
CREATE VIEW ref_list_directory AS
SELECT l.source_key, l.list_name, coalesce(l.concept_name, l.item_name) AS concept,
       l.list_key, l.item_name, l.concept_name, l.superseded_by, l.source_page, l.data_sets,
       f.release_label,
       coalesce(n.national_codes, 0) AS national_codes,
       coalesce(n.default_codes, 0)  AS default_codes,
       s.first_seen_at
  FROM meta_code_list l
  LEFT JOIN meta_current_fetch f ON f.source_key = l.source_key
  LEFT JOIN (SELECT source_key, list_name,
                    count(*) FILTER (WHERE code_kind = 'national') AS national_codes,
                    count(*) FILTER (WHERE code_kind = 'default')  AS default_codes
               FROM ref_code GROUP BY source_key, list_name) n
         ON n.source_key = l.source_key AND n.list_name = l.list_name
  LEFT JOIN (SELECT source_key, list_name, min(loaded_at) AS first_seen_at
               FROM meta_code_list GROUP BY source_key, list_name) s
         ON s.source_key = l.source_key AND s.list_name = l.list_name
 WHERE l.is_current = 1;
