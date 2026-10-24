function dob_write_json(path,value)
fid=fopen(path,'w','n','UTF-8');assert(fid>=0);g=onCleanup(@()fclose(fid));
fprintf(fid,'%s\n',jsonencode(value,PrettyPrint=true));
end
