"""Small curated lexicon for the deterministic fallbacks (JD keyword extraction when
models are unavailable, and the offline fake provider). Not used to judge truthfulness.
"""

TOOLS = [
    "Python", "SQL", "R", "Scala", "Java", "Go", "TypeScript", "JavaScript", "C++", "C#", "Rust",
    "Spark", "PySpark", "Hadoop", "Kafka", "Flink", "Airflow", "dbt", "Snowflake", "BigQuery",
    "Redshift", "Databricks", "Delta Lake", "PostgreSQL", "MySQL", "MongoDB", "Redis",
    "Elasticsearch", "pgvector", "AWS", "Azure", "GCP", "SageMaker", "Vertex AI", "Lambda",
    "S3", "EC2", "EKS", "Docker", "Kubernetes", "Terraform", "Jenkins", "GitHub Actions",
    "MLflow", "Kubeflow", "TensorFlow", "PyTorch", "scikit-learn", "XGBoost", "LightGBM",
    "Pandas", "NumPy", "Hugging Face", "LangChain", "LlamaIndex", "OpenAI", "Claude",
    "Tableau", "Power BI", "Looker", "Excel", "Salesforce", "SAP", "Jira", "FastAPI", "Django",
    "Flask", "React", "Next.js", "Node.js", "GraphQL", "REST", "Prometheus", "Grafana",
    "Datadog", "Great Expectations", "Collibra", "Alation", "Unity Catalog",
]

SKILLS = [
    "machine learning", "deep learning", "generative AI", "LLM", "NLP", "computer vision",
    "MLOps", "data engineering", "data governance", "data quality", "data modeling",
    "data architecture", "data strategy", "ETL", "ELT", "feature engineering",
    "A/B testing", "experimentation", "causal inference", "forecasting", "time series",
    "statistics", "recommendation systems", "churn prediction", "anomaly detection",
    "RAG", "prompt engineering", "agentic AI", "explainable AI", "responsible AI",
    "model monitoring", "observability", "CI/CD", "microservices", "distributed systems",
    "system design", "cloud architecture", "stream processing", "real-time analytics",
    "dashboarding", "business intelligence", "analytics", "product analytics",
    "stakeholder management", "cross-functional leadership", "people management",
    "mentoring", "roadmap", "budget ownership", "vendor management", "change management",
    "agile", "scrum", "communication", "strategy", "privacy", "security", "compliance",
    "GDPR", "HIPAA", "SOC 2", "cost optimization",
]

SYNONYMS = {
    "machine learning": ["ML"],
    "artificial intelligence": ["AI"],
    "natural language processing": ["NLP"],
    "Kubernetes": ["k8s"],
    "PostgreSQL": ["Postgres"],
    "large language models": ["LLMs", "LLM"],
    "A/B testing": ["A/B tests", "split testing"],
    "CI/CD": ["continuous integration", "continuous delivery"],
    "Google Cloud": ["GCP"],
    "Amazon Web Services": ["AWS"],
    "scikit-learn": ["sklearn"],
    "JavaScript": ["JS"],
    "TypeScript": ["TS"],
}

SECTION_HEADINGS = {
    "summary": ["summary", "profile", "professional summary", "about", "objective", "overview"],
    "experience": ["experience", "work experience", "professional experience", "employment",
                   "career history", "work history"],
    "education": ["education", "academic background", "qualifications"],
    "skills": ["skills", "technical skills", "core competencies", "competencies", "expertise",
               "technologies", "tools"],
    "certifications": ["certifications", "certificates", "licenses", "certifications & training"],
    "projects": ["projects", "selected projects", "key projects"],
    "achievements": ["achievements", "awards", "honors", "publications"],
}
