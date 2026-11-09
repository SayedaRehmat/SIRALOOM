# Combined VEP 115.2 + Ensembl API release 115 runtime requirements.
# Resolved versions belong in the generated architecture-specific Carton snapshots.
requires 'DBI';
requires 'Set::IntervalTree';
requires 'JSON';
requires 'Text::CSV';
requires 'DBD::mysql', '<= 4.050';
requires 'DBD::SQLite';
requires 'HTTP::Tiny';
requires 'IO::Compress::Gzip';
requires 'URI::Escape';
requires 'Config::IniFiles';
requires 'Gzip::Faster';
requires 'List::MoreUtils';
requires 'Bio::DB::BigFile';
requires 'Bio::DB::HTS';
requires 'Try::Tiny';
requires 'Sereal';
requires 'String::Approx';
requires 'XML::LibXML::Reader';
requires 'Date::Manip::Date';
requires 'Role::Tiny';
requires 'Bio::Perl';
