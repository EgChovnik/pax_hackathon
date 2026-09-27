-- db/init.sql — схема Postgres. Накатывается автоматически при первом
-- старте контейнера (пустой том). Прогноз здесь НЕ хранится — он лежит
-- в parquet и читается через DuckDB; Postgres — справочники, факт, коэфы.

create table routes (
  route_id       text primary key,
  name           text not null,
  transport_type text not null default 'bus',
  color          text,
  in_domain      boolean not null default true   -- из meta.json модели
);

create table stops (
  stop_id text primary key,
  name    text not null,
  lat     double precision not null,
  lon     double precision not null
);

create table route_stops (
  route_id text references routes,
  stop_id  text references stops,
  seq      int not null,
  primary key (route_id, stop_id)
);

create table vehicles (
  route_id text primary key references routes,
  capacity int not null,   -- мест в салоне
  count    int not null    -- машин на линии
);

-- факт для дообучения и графиков «факт vs прогноз»
create table pax_fact (
  route_id text,
  stop_id  text,
  ts_start timestamp,
  pax_in   real,
  pax_out  real,
  primary key (route_id, stop_id, ts_start)
);
create index on pax_fact (route_id, ts_start);

-- дефолты слайдеров; ML перезаписывает их из meta.json (make sync-meta)
create table coef_defaults (
  factor     text primary key,
  multiplier real not null,
  note       text
);

insert into coef_defaults values
  ('rain', 1.08, 'дождь > 0.1 мм/ч'),
  ('snow', 1.15, 'снегопад'),
  ('event', 1.30, 'событие в радиусе 1.5 км'),
  ('holiday', 0.62, 'праздничный день'),
  ('school_break', 0.85, 'школьные каникулы');

-- ── демо-справочники (маршруты как в прототипе фронтенда) ──
insert into routes values
  ('144','Автобус 144','bus','#1f5fd0',true),
  ('м27','Магистраль м27','bus','#8a5fd0',true),
  ('908','Автобус 908','bus','#1f9e8f',false);

insert into vehicles values ('144',90,12),('м27',110,14),('908',90,10);

insert into stops values
  ('144-0','Тёплый Стан',55.619,37.507),('144-1','Коньково',55.633,37.519),
  ('144-2','Калужская',55.657,37.540),('144-3','Ленинский проспект',55.707,37.586),
  ('144-4','Октябрьская',55.729,37.611),('144-5','Полянка',55.737,37.618),
  ('144-6','Боровицкая',55.750,37.609),('144-7','Охотный Ряд',55.757,37.616),
  ('144-8','Цветной бульвар',55.771,37.620),('144-9','Марьина Роща',55.794,37.616),
  ('м27-0','Фили',55.746,37.515),('м27-1','Кутузовская',55.740,37.534),
  ('м27-2','Киевская',55.743,37.567),('м27-3','Смоленская',55.747,37.583),
  ('м27-4','Арбатская',55.752,37.601),('м27-5','Лубянка',55.760,37.628),
  ('м27-6','Курская',55.758,37.660),('м27-7','Авиамоторная',55.752,37.717),
  ('м27-8','Перово',55.751,37.786),
  ('908-0','Каширская',55.655,37.649),('908-1','Кантемировская',55.636,37.657),
  ('908-2','Царицыно',55.620,37.669),('908-3','Люблино',55.676,37.761),
  ('908-4','Волжская',55.690,37.754),('908-5','Рязанский проспект',55.717,37.793),
  ('908-6','Выхино',55.716,37.818);

insert into route_stops
select r.route_id, s.stop_id, split_part(s.stop_id,'-',2)::int
from routes r join stops s on s.stop_id like r.route_id || '-%';
