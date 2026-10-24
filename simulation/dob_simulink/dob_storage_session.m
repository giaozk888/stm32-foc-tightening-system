function cleanup=dob_storage_session(c)
% C: is nearly full on this machine. Route this session's SDI repository to
% workspace D:, then restore preferences. Do NOT delete prior user runs or
% lower MathWorks free-space protection. No clear/clearPreferences calls.
folder=fullfile(c.build,'sdi_storage');if ~isfolder(folder),mkdir(folder);end
old=Simulink.sdi.getStorageLocation();record=Simulink.sdi.getRecordData();
Simulink.sdi.setStorageLocation(folder);Simulink.sdi.setRecordData(true);
cleanup=onCleanup(@()restore(old,record));
end
function restore(folder,record)
Simulink.sdi.setStorageLocation(folder);Simulink.sdi.setRecordData(record);
end
