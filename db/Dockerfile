FROM postgres:latest

ARG DB_USER
ARG DB_PASSWORD
ARG DB_DATABASE
ARG DB_PORT

COPY init.sql /init.sql
RUN sed -i 's/replaceUSER/'"$DB_USER"'/g' /init.sql
RUN sed -i 's/replacePASSWORD/'"$DB_PASSWORD"'/g' /init.sql
RUN sed -i 's/replaceDBNAME/'"$DB_DATABASE"'/g' /init.sql
RUN mv /init.sql /docker-entrypoint-initdb.d/init.sql

RUN echo 'Port='"$DB_PORT" >> /usr/share/postgresql/postgresql.conf.sample

CMD ["postgres"]
