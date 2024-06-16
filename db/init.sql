SELECT 'CREATE DATABASE replaceDBNAME' 
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'replaceDBNAME')\gexec
