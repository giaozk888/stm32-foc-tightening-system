function report=run_dob_simulink_suite(mode)
% User entry: stage-gated simulation + context-aware final metric reduction.
if nargin==0,mode="full";end
run_dob_validation(mode);
report=finalize_dob_results();
end
