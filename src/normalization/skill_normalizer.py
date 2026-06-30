"""
src/normalization/skill_normalizer.py
======================================

The most important normalizer.  Converts raw skill strings to canonical
skill names through a three-stage pipeline:

Stage 1 — Dictionary Aliases
    Exact + case-insensitive lookup against the :data:`CANONICAL_SKILLS`
    alias table.  Fastest; confidence = 1.0.

Stage 2 — RapidFuzz Fuzzy Matching
    ``rapidfuzz.process.extractOne`` using ``token_sort_ratio``.
    Applied when Stage 1 fails.  Threshold configurable
    (default: ``0.82``).  Confidence = ratio / 100.

Stage 3 — SentenceTransformer Semantic Similarity
    ``all-MiniLM-L6-v2`` embeddings + cosine similarity.
    Applied when Stage 2 is below threshold.  Lazy-loaded; gracefully
    degraded when ``sentence_transformers`` is not installed.
    Threshold configurable (default: ``0.78``).

Result
------
Each raw skill produces a :class:`SkillNormalizationResult` containing:
- ``canonical``    — the matched canonical skill name
- ``original``     — the raw input
- ``score``        — similarity score ``[0.0, 1.0]``
- ``method``       — which stage produced the match
- ``matched``      — ``True`` when a canonical match was found

The normalizer is **deterministic**: SBERT embeddings for the same
model and input always produce the same vector.

Configuration
-------------
``fuzzy_threshold`` (float, default 0.82):
    Minimum fuzzy ratio to accept a Stage 2 match.

``sbert_threshold`` (float, default 0.78):
    Minimum cosine similarity to accept a Stage 3 match.

``use_sbert`` (bool, default True):
    Disable Stage 3 entirely if you want purely dictionary/fuzzy.

``batch_size`` (int, default 64):
    Batch size for SBERT embedding generation.

``unknown_passthrough`` (bool, default True):
    When ``True``, unmatched skills are kept as-is.
    When ``False``, they are dropped.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from src.models import CanonicalRecord, NormalizationMethod
from src.normalization.base import BaseNormalizer
from src.normalization.utils import NormalizationResult, deduplicate

# ================================================================
# Canonical Skill Database
# ================================================================

#: Maps canonical skill name → list of aliases (all lowercase in the dict).
CANONICAL_SKILLS: dict[str, list[str]] = {
    # ── Languages ─────────────────────────────────────────────
    "Python":             ["python", "py", "python3", "python 3", "python2",
                           "cpython", "python programming", "python scripting"],
    "JavaScript":         ["javascript", "js", "ecmascript", "es6", "es2015",
                           "es2016", "es2017", "es2018", "es2019", "es2020",
                           "vanilla js", "vanilla javascript"],
    "TypeScript":         ["typescript", "ts", "typescript language"],
    "Java":               ["java", "java se", "java ee", "java 8", "java 11",
                           "java 17", "java programming", "core java"],
    "C++":                ["c++", "cpp", "c plus plus", "c/c++"],
    "C#":                 ["c#", "csharp", "c sharp", "c# .net", "dotnet csharp"],
    "C":                  ["c", "c language", "c programming", "ansi c"],
    "Go":                 ["go", "golang", "go lang", "go programming"],
    "Rust":               ["rust", "rust lang", "rust programming"],
    "Ruby":               ["ruby", "ruby lang", "ruby programming"],
    "PHP":                ["php", "php7", "php8", "php programming"],
    "Swift":              ["swift", "swift programming", "swift language"],
    "Kotlin":             ["kotlin", "kotlin programming"],
    "Scala":              ["scala", "scala programming"],
    "R":                  ["r", "r language", "rlang", "r programming",
                           "r statistical"],
    "MATLAB":             ["matlab", "matlab programming"],
    "Julia":              ["julia", "julia lang"],
    "Perl":               ["perl", "perl programming"],
    "Haskell":            ["haskell", "haskell programming"],
    "Elixir":             ["elixir", "elixir lang"],
    "Erlang":             ["erlang"],
    "Dart":               ["dart", "dart programming"],
    "Lua":                ["lua", "lua scripting"],
    "Groovy":             ["groovy", "groovy lang"],
    "Shell":              ["shell", "bash", "bash scripting", "shell scripting",
                           "sh", "zsh", "ksh", "posix shell"],
    "PowerShell":         ["powershell", "pwsh"],
    "Assembly":           ["assembly", "asm", "assembly language"],
    "COBOL":              ["cobol"],
    "Fortran":            ["fortran"],
    "Objective-C":        ["objective-c", "objc", "objective c"],
    "VBA":                ["vba", "visual basic for applications", "visual basic"],

    # ── Web Frameworks ────────────────────────────────────────
    "React":              ["react", "reactjs", "react.js", "react js",
                           "react library", "react hooks", "react native"],
    "Angular":            ["angular", "angularjs", "angular.js", "angular 2+",
                           "angular framework"],
    "Vue.js":             ["vue", "vuejs", "vue.js", "vue js", "vue 3",
                           "vue 2", "vuex"],
    "Next.js":            ["next", "nextjs", "next.js", "next js"],
    "Nuxt.js":            ["nuxt", "nuxtjs", "nuxt.js"],
    "Svelte":             ["svelte", "sveltekit"],
    "Ember.js":           ["ember", "emberjs", "ember.js"],
    "Backbone.js":        ["backbone", "backbonejs"],
    "jQuery":             ["jquery", "jquery.js"],
    "Bootstrap":          ["bootstrap", "bootstrap css"],
    "Tailwind CSS":       ["tailwind", "tailwindcss", "tailwind css"],
    "Sass":               ["sass", "scss"],
    "Node.js":            ["node", "nodejs", "node.js", "node js", "node server"],
    "Express":            ["express", "expressjs", "express.js", "express framework"],
    "Fastify":            ["fastify"],
    "NestJS":             ["nestjs", "nest.js", "nest js"],
    "Django":             ["django", "django framework", "django rest framework",
                           "drf"],
    "Flask":              ["flask", "flask framework", "flask python"],
    "FastAPI":            ["fastapi", "fast api", "fastapi python"],
    "Spring":             ["spring", "spring boot", "spring framework",
                           "spring mvc", "spring data", "spring security"],
    "Hibernate":          ["hibernate", "hibernate orm"],
    "Rails":              ["rails", "ruby on rails", "ror"],
    "Laravel":            ["laravel", "laravel php"],
    "Symfony":            ["symfony", "symfony framework"],
    "ASP.NET":            ["asp.net", "aspnet", "asp.net core", "asp.net mvc",
                           "asp.net web api"],
    "Blazor":             ["blazor"],

    # ── ML / AI ───────────────────────────────────────────────
    "TensorFlow":         ["tensorflow", "tf", "tensorflow2", "tensorflow 2",
                           "tensorflow 1", "tensorflow lite", "tensorflow.js"],
    "PyTorch":            ["pytorch", "torch", "pytorch lightning",
                           "pytorch framework"],
    "Keras":              ["keras"],
    "scikit-learn":       ["sklearn", "scikit learn", "scikit-learn",
                           "sci-kit learn", "scikit"],
    "Pandas":             ["pandas", "pd", "pandas python"],
    "NumPy":              ["numpy", "np", "numpy python"],
    "SciPy":              ["scipy"],
    "Matplotlib":         ["matplotlib", "matplotlib python"],
    "Seaborn":            ["seaborn"],
    "Plotly":             ["plotly", "plotly dash", "dash"],
    "XGBoost":            ["xgboost", "xgb", "extreme gradient boosting"],
    "LightGBM":           ["lightgbm", "lgbm", "light gbm"],
    "CatBoost":           ["catboost"],
    "Hugging Face":       ["huggingface", "hugging face", "transformers",
                           "hugging face transformers"],
    "BERT":               ["bert", "bert model", "google bert"],
    "GPT":                ["gpt", "gpt-3", "gpt-4", "chatgpt", "openai gpt"],
    "LangChain":          ["langchain", "lang chain"],
    "OpenCV":             ["opencv", "open cv", "cv2"],
    "NLTK":               ["nltk", "natural language toolkit"],
    "spaCy":              ["spacy", "spacy python"],
    "Statsmodels":        ["statsmodels"],
    "MLflow":             ["mlflow", "ml flow"],
    "Kubeflow":           ["kubeflow"],
    "Airflow":            ["airflow", "apache airflow"],

    # ── Cloud ─────────────────────────────────────────────────
    "AWS":                ["aws", "amazon web services", "amazon aws",
                           "aws cloud", "amazon cloud"],
    "Google Cloud":       ["gcp", "google cloud", "google cloud platform",
                           "google cloud services", "gcp cloud"],
    "Azure":              ["azure", "microsoft azure", "azure cloud",
                           "ms azure", "azure services"],
    "AWS Lambda":         ["lambda", "aws lambda", "serverless lambda"],
    "AWS S3":             ["s3", "aws s3", "amazon s3"],
    "AWS EC2":            ["ec2", "aws ec2", "amazon ec2"],
    "AWS ECS":            ["ecs", "aws ecs", "elastic container service"],
    "AWS EKS":            ["eks", "aws eks", "elastic kubernetes service"],
    "AWS RDS":            ["rds", "aws rds"],
    "AWS SageMaker":      ["sagemaker", "aws sagemaker", "amazon sagemaker"],
    "Azure DevOps":       ["azure devops", "ado"],
    "Firebase":           ["firebase", "google firebase"],
    "Heroku":             ["heroku"],
    "Vercel":             ["vercel"],
    "Netlify":            ["netlify"],
    "DigitalOcean":       ["digitalocean", "digital ocean", "do"],

    # ── DevOps / Infra ────────────────────────────────────────
    "Docker":             ["docker", "docker container", "docker compose",
                           "docker swarm", "dockerfile"],
    "Kubernetes":         ["kubernetes", "k8s", "kube", "kubernetes cluster",
                           "k8"],
    "Terraform":          ["terraform", "tf", "hashicorp terraform",
                           "terraform iac"],
    "Ansible":            ["ansible"],
    "Puppet":             ["puppet"],
    "Chef":               ["chef"],
    "Jenkins":            ["jenkins", "jenkins ci", "jenkins pipeline"],
    "GitHub Actions":     ["github actions", "gh actions", "github action"],
    "GitLab CI":          ["gitlab ci", "gitlab ci/cd", "gitlab pipeline"],
    "CircleCI":           ["circleci", "circle ci"],
    "Travis CI":          ["travis ci", "travisci"],
    "ArgoCD":             ["argocd", "argo cd"],
    "Helm":               ["helm", "helm chart", "helm charts"],
    "Prometheus":         ["prometheus"],
    "Grafana":            ["grafana"],
    "Datadog":            ["datadog"],
    "New Relic":          ["new relic", "newrelic"],
    "ELK Stack":          ["elk", "elk stack", "elasticsearch logstash kibana"],
    "Nginx":              ["nginx"],
    "HAProxy":            ["haproxy"],
    "Vault":              ["vault", "hashicorp vault"],
    "Consul":             ["consul", "hashicorp consul"],
    "Istio":              ["istio", "istio service mesh"],

    # ── Databases ─────────────────────────────────────────────
    "PostgreSQL":         ["postgresql", "postgres", "psql", "pg",
                           "postgresql database", "postgres db"],
    "MySQL":              ["mysql", "mysql database", "mysql db"],
    "SQLite":             ["sqlite", "sqlite3"],
    "Microsoft SQL Server": ["mssql", "sql server", "microsoft sql server",
                             "ms sql", "tsql", "t-sql"],
    "Oracle":             ["oracle", "oracle db", "oracle database",
                           "oracle pl/sql", "plsql"],
    "MongoDB":            ["mongodb", "mongo", "mongodb atlas", "nosql mongodb"],
    "Redis":              ["redis", "redis cache", "redis db"],
    "Elasticsearch":      ["elasticsearch", "elastic", "es", "elastic search"],
    "Cassandra":          ["cassandra", "apache cassandra"],
    "DynamoDB":           ["dynamodb", "aws dynamodb", "amazon dynamodb"],
    "Firestore":          ["firestore", "cloud firestore"],
    "InfluxDB":           ["influxdb", "influx db"],
    "Neo4j":              ["neo4j", "neo 4j", "graph database"],
    "CouchDB":            ["couchdb", "couch db"],
    "Supabase":           ["supabase"],
    "BigQuery":           ["bigquery", "big query", "google bigquery"],
    "Snowflake":          ["snowflake", "snowflake db"],
    "Redshift":           ["redshift", "aws redshift", "amazon redshift"],
    "dbt":                ["dbt", "data build tool"],
    "Apache Spark":       ["spark", "apache spark", "pyspark"],
    "Apache Kafka":       ["kafka", "apache kafka"],
    "Apache Flink":       ["flink", "apache flink"],
    "Apache Hadoop":      ["hadoop", "apache hadoop", "hdfs", "mapreduce"],
    "Hive":               ["hive", "apache hive"],

    # ── Concepts / Practices ──────────────────────────────────
    "Machine Learning":   ["ml", "machine learning", "machine-learning",
                           "ml modeling", "machine learning models"],
    "Deep Learning":      ["dl", "deep learning", "deep-learning",
                           "neural networks", "neural network"],
    "Natural Language Processing": ["nlp", "natural language processing",
                                    "text mining", "computational linguistics"],
    "Computer Vision":    ["cv", "computer vision", "image recognition",
                           "object detection"],
    "Data Science":       ["data science", "data scientist", "data analytics"],
    "Data Engineering":   ["data engineering", "data engineer", "data pipeline"],
    "MLOps":              ["mlops", "ml ops", "ml operations"],
    "DevOps":             ["devops", "dev ops", "devsecops", "devops engineering"],
    "CI/CD":              ["cicd", "ci cd", "ci/cd", "continuous integration",
                           "continuous deployment", "continuous delivery",
                           "cd pipeline"],
    "Microservices":      ["microservices", "micro services", "microservice",
                           "microservice architecture"],
    "REST API":           ["rest", "rest api", "restful", "restful api",
                           "rest apis", "restful services"],
    "GraphQL":            ["graphql", "graph ql", "graphql api"],
    "gRPC":               ["grpc", "g rpc", "grpc api"],
    "WebSockets":         ["websockets", "websocket", "ws"],
    "System Design":      ["system design", "system architecture",
                           "distributed systems", "large scale systems"],
    "Agile":              ["agile", "scrum", "kanban", "agile methodology",
                           "agile development"],
    "TDD":                ["tdd", "test driven development",
                           "test-driven development"],
    "Object-Oriented Programming": ["oop", "object oriented programming",
                                    "object-oriented programming",
                                    "object oriented design"],
    "Functional Programming": ["functional programming", "fp",
                               "functional design"],

    # ── Tools ─────────────────────────────────────────────────
    "Git":                ["git", "version control", "git version control"],
    "GitHub":             ["github", "gh"],
    "GitLab":             ["gitlab"],
    "Bitbucket":          ["bitbucket"],
    "JIRA":               ["jira", "jira software", "atlassian jira"],
    "Confluence":         ["confluence", "atlassian confluence"],
    "Slack":              ["slack"],
    "Figma":              ["figma", "figma design"],
    "Linux":              ["linux", "ubuntu", "debian", "centos", "rhel",
                           "fedora", "arch linux", "linux administration"],
    "Windows":            ["windows", "windows server", "win32"],
    "macOS":              ["macos", "mac os", "osx", "os x"],
    "HTML":               ["html", "html5", "hypertext markup language"],
    "CSS":                ["css", "css3", "cascading style sheets"],
    "SQL":                ["sql", "structured query language",
                           "sql queries", "sql databases"],
    "NoSQL":              ["nosql", "no sql", "non relational database"],
    "Jupyter":            ["jupyter", "jupyter notebook", "jupyter lab",
                           "ipython notebook"],
    "VS Code":            ["vscode", "vs code", "visual studio code"],
    "IntelliJ":           ["intellij", "intellij idea"],
    "Eclipse":            ["eclipse ide", "eclipse"],
    "Postman":            ["postman", "postman api"],
    "Swagger":            ["swagger", "swagger ui", "openapi"],
    "RabbitMQ":           ["rabbitmq", "rabbit mq"],
    "Celery":             ["celery", "celery python"],
    "Redux":              ["redux", "redux.js", "react redux"],
    "Jest":               ["jest", "jest testing"],
    "Pytest":             ["pytest", "py.test"],
    "JUnit":              ["junit", "junit5", "junit 5"],
    "Selenium":           ["selenium", "selenium webdriver"],
    "Cypress":            ["cypress", "cypress.io"],
    "Playwright":         ["playwright"],
}

# Build lowercase alias → canonical mapping
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in CANONICAL_SKILLS.items():
    for _alias in _aliases:
        _ALIAS_TO_CANONICAL[_alias.lower()] = _canonical
    # canonical itself
    _ALIAS_TO_CANONICAL[_canonical.lower()] = _canonical

_CANONICAL_NAMES: list[str] = list(CANONICAL_SKILLS.keys())


# ================================================================
# SkillNormalizationResult
# ================================================================


@dataclass
class SkillNormalizationResult:
    """
    Result of normalizing a single skill string.

    Attributes
    ----------
    original:
        Raw skill string.
    canonical:
        Matched canonical skill name, or the original when unmatched.
    score:
        Similarity score ``[0.0, 1.0]``.
    method:
        The :class:`~src.models.NormalizationMethod` used.
    matched:
        ``True`` when a canonical match was found above threshold.
    """

    original:  str
    canonical: str
    score:     float
    method:    NormalizationMethod
    matched:   bool


# ================================================================
# SBERT lazy loader
# ================================================================


class _SBERTModel:
    """Lazy singleton for the SentenceTransformer model."""

    _model: Any = None
    _embeddings: dict[str, Any] = {}

    @classmethod
    def get(cls) -> Any:
        if cls._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                cls._model = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                cls._model = False  # sentinel: not available
        return cls._model if cls._model is not False else None

    @classmethod
    def get_canonical_embeddings(cls, batch_size: int = 64) -> "dict[str, Any] | None":
        """
        Return pre-computed embeddings for all canonical skill names.
        Computed once and cached.
        """
        model = cls.get()
        if model is None:
            return None
        if not cls._embeddings:
            import numpy as np
            vecs = model.encode(_CANONICAL_NAMES, batch_size=batch_size,
                                convert_to_numpy=True, show_progress_bar=False)
            cls._embeddings = {name: vec for name, vec in zip(_CANONICAL_NAMES, vecs)}
        return cls._embeddings


# ================================================================
# Skill normalization functions
# ================================================================


def _clean_skill(raw: str) -> str:
    """Lowercase, strip, collapse whitespace, remove punctuation noise."""
    s = unicodedata.normalize("NFC", raw).lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s.#+\-/]", "", s)
    return s.strip()


def _stage1_lookup(raw: str) -> SkillNormalizationResult | None:
    """Exact alias lookup."""
    key = _clean_skill(raw)
    if key in _ALIAS_TO_CANONICAL:
        canonical = _ALIAS_TO_CANONICAL[key]
        return SkillNormalizationResult(
            original=raw, canonical=canonical,
            score=1.0, method=NormalizationMethod.SKILL_ALIAS, matched=True,
        )
    return None


def _stage2_fuzzy(raw: str, threshold: float) -> SkillNormalizationResult | None:
    """RapidFuzz token-sort matching against canonical names."""
    try:
        from rapidfuzz import process, fuzz
    except ImportError:
        return None

    cleaned = _clean_skill(raw)
    # Try aliases first
    alias_result = process.extractOne(
        cleaned, list(_ALIAS_TO_CANONICAL.keys()),
        scorer=fuzz.token_sort_ratio,
        score_cutoff=threshold * 100,
    )
    if alias_result:
        matched_alias, score, _ = alias_result
        canonical = _ALIAS_TO_CANONICAL[matched_alias]
        return SkillNormalizationResult(
            original=raw, canonical=canonical,
            score=score / 100.0,
            method=NormalizationMethod.SKILL_FUZZY, matched=True,
        )

    # Then canonical names
    name_result = process.extractOne(
        cleaned, _CANONICAL_NAMES,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=threshold * 100,
    )
    if name_result:
        matched_name, score, _ = name_result
        return SkillNormalizationResult(
            original=raw, canonical=matched_name,
            score=score / 100.0,
            method=NormalizationMethod.SKILL_FUZZY, matched=True,
        )
    return None


def _stage3_sbert(
    raw: str,
    threshold: float,
    batch_size: int,
) -> SkillNormalizationResult | None:
    """SentenceTransformer cosine similarity matching."""
    model = _SBERTModel.get()
    if model is None:
        return None

    canonical_embeddings = _SBERTModel.get_canonical_embeddings(batch_size)
    if not canonical_embeddings:
        return None

    try:
        import numpy as np
        cleaned = _clean_skill(raw)
        query_vec = model.encode([cleaned], convert_to_numpy=True,
                                 show_progress_bar=False)[0]
        # Cosine similarity
        names = _CANONICAL_NAMES
        vecs  = np.array([canonical_embeddings[n] for n in names])
        norm_q = np.linalg.norm(query_vec)
        if norm_q == 0:
            return None
        norm_v = np.linalg.norm(vecs, axis=1)
        valid  = norm_v > 0
        sims   = np.where(valid, vecs.dot(query_vec) / (norm_v * norm_q), 0.0)
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])

        if best_sim >= threshold:
            return SkillNormalizationResult(
                original=raw, canonical=names[best_idx],
                score=best_sim,
                method=NormalizationMethod.SKILL_SBERT, matched=True,
            )
    except Exception:
        pass
    return None


def normalize_skill(
    raw: str,
    *,
    fuzzy_threshold: float = 0.82,
    sbert_threshold: float = 0.78,
    use_sbert: bool = True,
    batch_size: int = 64,
) -> SkillNormalizationResult:
    """
    Normalize a single raw skill string through the three-stage pipeline.

    Parameters
    ----------
    raw:
        Raw skill string.
    fuzzy_threshold:
        Minimum ratio for Stage 2 fuzzy match ``[0.0, 1.0]``.
    sbert_threshold:
        Minimum cosine similarity for Stage 3 SBERT match ``[0.0, 1.0]``.
    use_sbert:
        Enable Stage 3 semantic matching.
    batch_size:
        Batch size for SBERT canonical embedding computation.

    Returns
    -------
    SkillNormalizationResult
        Best match result.  ``matched=False`` when all stages fail.
    """
    if not raw or not raw.strip():
        return SkillNormalizationResult(
            original=raw, canonical=raw,
            score=0.0, method=NormalizationMethod.NONE, matched=False,
        )

    # Stage 1
    r = _stage1_lookup(raw)
    if r:
        return r

    # Stage 2
    r = _stage2_fuzzy(raw, fuzzy_threshold)
    if r:
        return r

    # Stage 3
    if use_sbert:
        r = _stage3_sbert(raw, sbert_threshold, batch_size)
        if r:
            return r

    # Unmatched
    return SkillNormalizationResult(
        original=raw, canonical=raw,
        score=0.0, method=NormalizationMethod.NONE, matched=False,
    )


# ================================================================
# SkillNormalizer (record-level)
# ================================================================


class SkillNormalizer(BaseNormalizer):
    """
    Normalizes :attr:`~src.models.CanonicalRecord.skills` using the
    three-stage pipeline.

    Config Keys
    -----------
    ``fuzzy_threshold`` (float, default ``0.82``):
        Minimum RapidFuzz ratio to accept Stage 2 result.
    ``sbert_threshold`` (float, default ``0.78``):
        Minimum SBERT cosine similarity to accept Stage 3 result.
    ``use_sbert`` (bool, default ``True``):
        Enable Stage 3.
    ``batch_size`` (int, default ``64``):
        SBERT batch size.
    ``unknown_passthrough`` (bool, default ``True``):
        Keep unmatched skills as-is.
    ``deduplicate`` (bool, default ``True``):
        Deduplicate normalized skill list.
    """

    def supports(self, record: CanonicalRecord) -> bool:
        return bool(record.skills)

    def metadata(self) -> dict[str, Any]:
        return {
            "normalizer":       self.__class__.__name__,
            "fields":           ["skills"],
            "method":           "ALIAS → FUZZY → SBERT",
            "canonical_count":  len(CANONICAL_SKILLS),
            "alias_count":      len(_ALIAS_TO_CANONICAL),
            "version":          "1.0.0",
        }

    def normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        return self._timed_normalize(record, self._do_normalize)

    def _do_normalize(self, record: CanonicalRecord) -> CanonicalRecord:
        fuzzy_threshold   = float(self._config.get("fuzzy_threshold",   0.82))
        sbert_threshold   = float(self._config.get("sbert_threshold",   0.78))
        use_sbert         = bool(self._config.get("use_sbert",          True))
        batch_size        = int(self._config.get("batch_size",          64))
        unknown_pass      = bool(self._config.get("unknown_passthrough", True))
        do_dedup          = bool(self._config.get("deduplicate",         True))

        original_skills = list(record.skills)
        normalized_skills: list[str] = []

        for raw_skill in original_skills:
            result = normalize_skill(
                raw_skill,
                fuzzy_threshold=fuzzy_threshold,
                sbert_threshold=sbert_threshold,
                use_sbert=use_sbert,
                batch_size=batch_size,
            )

            if result.matched:
                normalized_skills.append(result.canonical)
                if result.canonical != raw_skill:
                    self._add_provenance(
                        record,
                        field="skills",
                        original_value=raw_skill,
                        normalized_value=result.canonical,
                        method=result.method,
                        confidence=result.score,
                        reason=(
                            f"[{result.method.value}] {raw_skill!r} → "
                            f"{result.canonical!r} (score={result.score:.3f})"
                        ),
                    )
            else:
                self._log.warning(
                    "Skill not matched to canonical",
                    extra={
                        "raw_skill": raw_skill,
                        "source":    record.source_label,
                    },
                )
                if unknown_pass:
                    normalized_skills.append(raw_skill)

        if do_dedup:
            normalized_skills = deduplicate(normalized_skills, key=str.lower)

        record.skills = normalized_skills
        return record
