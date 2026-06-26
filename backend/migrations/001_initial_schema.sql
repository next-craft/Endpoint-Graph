CREATE TABLE public.services (
  id          SERIAL PRIMARY KEY,
  name        VARCHAR(100) NOT NULL,
  language    VARCHAR(50),
  repo_url    VARCHAR(255),
  created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE public.endpoints (
  id           SERIAL PRIMARY KEY,
  service_id   INT NOT NULL REFERENCES public.services(id) ON DELETE CASCADE,
  method       VARCHAR(10) NOT NULL,
  path         VARCHAR(255) NOT NULL,
  spec_source  VARCHAR(50),
  created_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE public.consumer_edges (
  id                 SERIAL PRIMARY KEY,
  caller_service_id  INT NOT NULL REFERENCES public.services(id) ON DELETE CASCADE,
  endpoint_id        INT NOT NULL REFERENCES public.endpoints(id) ON DELETE CASCADE,
  last_seen_at       TIMESTAMP DEFAULT NOW(),
  call_count         INT DEFAULT 0,
  source             VARCHAR(20) NOT NULL,
  created_at         TIMESTAMP DEFAULT NOW(),
  UNIQUE(caller_service_id, endpoint_id)
);
