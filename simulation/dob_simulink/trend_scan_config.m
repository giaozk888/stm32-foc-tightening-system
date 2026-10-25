function q=trend_scan_config()
% Fixed 2x2 experiment; no modification of phase1_config or MCU parameters.
q.ids=["tau100_dwell80","tau100_dwell40","tau50_dwell80","tau50_dwell40"];
q.tau_ms=[100 100 50 50];q.dwell_ms=[80 40 80 40];
q.seeds=[1:5,61:65];q.eval_s=[2.3 6.9];q.event_match_max_s=.8;
q.baseline_results='20261024_114423';
q.accept.real_transition_ratio_max=1.25;
q.accept.extra_unmatched_events_max=0;
q.accept.minimum_event_hits_ratio=1;
q.selection='first5 train, last5 held-out; no fallback retuning on held-out';
end
