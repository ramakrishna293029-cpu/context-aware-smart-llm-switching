"""Feature extraction engine for LinUCB contextual bandit routing.

Provides fast, lightweight TF-IDF + TruncatedSVD dimensionality reduction
mapping user prompts and conversation history into 16-dimensional normalized
contextual vectors for multi-armed bandit exploration and exploitation.
"""

from typing import Any, List, Optional
import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer


# ---------------------------------------------------------------------------
# Rich Multi-Domain Seed Corpus
# Spanning Software Engineering, Math/Logic, Conversational/QA, and System Design
# ---------------------------------------------------------------------------

SEED_CORPUS: List[str] = [
    # 1. Code / Software Engineering (Python, C++, SQL, Git, async, algorithms, errors)
    "def asynchronous_task(items: list[str]) -> list: async with httpx.AsyncClient() as client: return await asyncio.gather(*[client.get(u) for u in items])",
    "class DataPipeline(BaseModel): @classmethod def register_handler(cls, func: Callable): def wrapper(*args, **kwargs): return func(*args, **kwargs)",
    "Python generator coroutine yield yield from typing List Dict Optional Any asyncio event loop task future exception handling pytest fixtures",
    "#include <iostream> #include <vector> #include <memory> template<typename T> class SmartPointer { std::unique_ptr<T> ptr; public: explicit SmartPointer(T* val) : ptr(val) {} };",
    "C++ memory management, std::shared_ptr, std::unique_ptr, RAII, pointers, references, virtual destructor, segmentation fault core dumped, valgrind memory leak",
    "Multithreading in C++, std::thread, std::mutex, std::lock_guard, std::atomic, race condition, deadlock, lock-free queue, memory barrier, cache coherency",
    "SELECT orders.id, customer.name, SUM(orders.amount) AS total FROM orders INNER JOIN customer ON orders.cust_id = customer.id WHERE orders.created_at >= '2026-01-01' GROUP BY orders.id, customer.name HAVING total > 1000 ORDER BY total DESC LIMIT 50;",
    "CREATE INDEX idx_user_email ON users(email); BEGIN TRANSACTION; UPDATE accounts SET balance = balance - 100 WHERE id = 1; COMMIT; rollback savepoint isolation serializable",
    "git checkout -b feature-branch && git add . && git commit -m 'feat: implement linucb router' && git rebase main && git push origin -f",
    "Auto-merging router.py CONFLICT (content): Merge conflict in router.py. Automatic merge failed; fix conflicts and then commit the result. git cherry-pick git stash",
    "Implement Dijkstra shortest path algorithm using a priority queue min-heap. Time complexity O((V + E) log V), space complexity O(V). Graph adjacency list.",
    "Dynamic programming bottom-up tabulation memoization: def longest_common_subsequence(text1: str, text2: str) -> int: dp = [[0] * (n + 1) for _ in range(m + 1)]",
    "Binary search tree BST balancing, AVL tree rotation, Red-Black tree self balancing, in-order traversal, post-order traversal, graph breadth first search BFS depth first search DFS",
    "Traceback (most recent call last): File 'main.py', line 42, in <module> ZeroDivisionError: division by zero. TypeError: unsupported operand type(s) KeyError IndexError NullPointerException",
    "Rust borrow checker lifetimes ownership reference &mut struct impl trait Result Option unwrap pattern matching cargo build",
    "Frontend web development React TypeScript useEffect useState Redux DOM rendering CSS Flexbox Tailwind HTML5 bundle webpack",

    # 2. Mathematics / Logic / Reasoning (proofs, calculus, discrete math, statistics)
    "Theorem: For every integer n >= 1, the sum of the first n integers is n(n+1)/2. Proof by mathematical induction: base case n=1, inductive step assume true for k, prove k+1.",
    "Prove by contradiction that sqrt(2) is irrational. Assume sqrt(2) = a/b where a and b are coprime integers. Then 2 = a^2 / b^2, so a^2 is even, contradiction.",
    "Differential calculus: compute derivative of f(x) = sin(x^2) / e^(3x) using quotient rule and chain rule. Partial derivatives, gradient vector, Hessian matrix, Taylor series expansion.",
    r"Integral calculus: evaluate definite integral \int_{0}^{\pi} x sin(x) dx using integration by parts where u = x, dv = sin(x) dx, v = -cos(x). Riemann sum fundamental theorem.",
    "Solve second-order ordinary differential equation ODE: y'' - 5y' + 6y = 0. Characteristic polynomial r^2 - 5r + 6 = 0 yields roots r=2, r=3, general solution y(t) = c1 e^(2t) + c2 e^(3t).",
    "Discrete mathematics: combinatorics, permutations, combinations n choose k = n! / (k!(n-k)!), binomial theorem, Pascal triangle, pigeonhole principle, inclusion-exclusion principle.",
    "Probability theory: Bayes theorem calculates posterior probability P(A|B) = P(B|A) * P(A) / P(B). Prior probability, likelihood ratio, marginal evidence, independent random variables.",
    "Statistical inference: null hypothesis H0 testing, p-value < 0.05, Student's t-test, ANOVA, chi-square goodness of fit, standard normal distribution, central limit theorem, confidence interval.",
    "Propositional logic: modus ponens, modus tollens, tautology, contradiction, truth tables, logical connectives conjunction disjunction negation implication, boolean algebra satisfiability.",
    "Analytical reasoning puzzle: Alice, Bob, and Charlie make statements. Exactly one is lying. Deduce who committed the crime through elimination and logical deduction.",
    "Linear algebra: eigenvalues, eigenvectors, singular value decomposition SVD, matrix rank, determinant, orthogonal projection, dot product, vector space basis.",
    "Abstract algebra and number theory: modular arithmetic, Fermat's little theorem, Chinese remainder theorem, prime factorization, RSA cryptography, group theory isomorphism.",

    # 3. Conversational / Greetings / Simple QA (hi, hello, weather, facts, thank you)
    "Hi, hello there! How are you doing today? Good morning! Good afternoon! Good evening! Hope you are doing well.",
    "Hey! What's up? How is your day going? Just checking in, hope everything is fantastic with you. How can I assist you?",
    "Thank you so much for your help! I really appreciate your assistance. Have a wonderful weekend, goodbye, see you later!",
    "You are very welcome! Glad I could help. Let me know if you need anything else. Take care and have a great day!",
    "What is the capital city of France? Paris is the capital and largest city of France, known for the Eiffel Tower, Louvre Museum, and Seine River.",
    "What is the weather like outside today? Is it sunny, cloudy, or going to rain? Check the forecast, temperature, and precipitation.",
    "What is the definition of photosynthesis? Photosynthesis is the biological process by which green plants convert light energy into chemical energy to synthesize food.",
    "Tell me a fun trivia fact or a lighthearted joke to brighten my day! Who won the FIFA World Cup in 2022? Argentina won against France.",
    "How can I boil an egg so the yolk stays soft and runny? Bring water to a boil, gently lower eggs, cook for 6 minutes, then transfer to an ice bath.",
    "What time is it right now in Tokyo, Japan? Tokyo is in Japan Standard Time UTC+9. Good day, please, excuse me, cheers.",
    "Can you recommend a quick healthy breakfast recipe? Overnight oats with chia seeds, almond milk, sliced bananas, and honey.",
    "Who painted the Mona Lisa? Leonardo da Vinci painted the Mona Lisa during the Italian Renaissance in the early 16th century.",

    # 4. Architecture / System Design (microservices, distributed systems, caching, databases)
    "Microservices architecture: decomposing monolith into decoupled autonomous microservices communicating via RESTful JSON APIs and gRPC with an API Gateway pattern.",
    "Distributed consensus protocols: Raft leader election, log replication, and safety guarantees vs Paxos algorithm. Handling network partitions, split-brain, and node failures.",
    "CAP theorem trade-offs: consistency, availability, and partition tolerance in distributed databases. PACELC theorem, eventual consistency, read-your-writes, quorum consensus.",
    "Distributed caching architecture: Redis cluster and Memcached using cache-aside pattern, write-through, write-back, cache invalidation, cache stampede thundering herd, TTL, LRU eviction.",
    "Database design: relational SQL vs NoSQL document stores MongoDB, wide-column Cassandra, key-value DynamoDB, schema normalization, B-tree indexes vs LSM trees.",
    "Database horizontal sharding: partitioning data across shards by partition key, consistent hashing ring with virtual nodes, cross-shard queries, distributed two-phase commit 2PC.",
    "Event-driven architecture: message brokers Apache Kafka and RabbitMQ, high-throughput log streaming, consumer groups, partition rebalancing, message deduplication, event sourcing CQRS.",
    "High availability and fault tolerance: Nginx reverse proxy load balancer, round-robin, least connections, auto-scaling groups, health checks, circuit breaker pattern, CDN edge caching.",
    "Rate limiting and traffic shaping: token bucket algorithm, leaky bucket algorithm, sliding window counter, API rate limiter with Redis and distributed locks.",
    "Security architecture: OAuth2, OpenID Connect, JWT tokens, asymmetric RSA signing, HTTPS TLS encryption, role-based access control RBAC, SQL injection prevention, CORS."
]


class ContextFeatureExtractor:
    """Feature extraction engine for LinUCB bandit context vectors.

    Converts input query and conversation history into a 16-dimensional
    normalized feature vector (norm == 1.0) using pre-trained TF-IDF
    and TruncatedSVD components.
    """

    def __init__(self, seed_corpus: Optional[List[str]] = None):
        """Initializes and fits TF-IDF Vectorizer and TruncatedSVD."""
        corpus = seed_corpus if seed_corpus is not None else SEED_CORPUS

        self._vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            sublinear_tf=True,
            strip_accents="unicode",
        )
        tfidf_matrix = self._vectorizer.fit_transform(corpus)

        self._svd = TruncatedSVD(n_components=16, random_state=42)
        self._svd.fit(tfidf_matrix)

        # Precompute guaranteed unit-norm fallback vector for empty or zero inputs
        self._fallback_vector: np.ndarray = np.ones(16, dtype=np.float64) / np.sqrt(16.0)

    @property
    def fallback_vector(self) -> np.ndarray:
        """Returns the uniform unit vector fallback."""
        return self._fallback_vector.copy()

    def _extract_history_text(self, history: Optional[List[Any]]) -> List[str]:
        """Safely extracts text strings from heterogeneous history representations."""
        if not history:
            return []

        segments: List[str] = []
        for item in history:
            if item is None:
                continue
            if isinstance(item, str):
                text = item.strip()
            elif hasattr(item, "content"):
                val = getattr(item, "content")
                text = str(val).strip() if val is not None else ""
            elif isinstance(item, dict):
                val = item.get("content", "")
                text = str(val).strip() if val is not None else ""
            else:
                text = str(item).strip()

            if text:
                segments.append(text)
        return segments

    def extract(self, query: str, history: Optional[List[Any]] = None) -> np.ndarray:
        """Extracts a 16-dimensional unit-norm feature vector from query and history.

        Args:
            query: The user prompt string.
            history: Optional list of prior conversational messages (strings, dicts, or ChatMessage objects).

        Returns:
            np.ndarray of shape (16,) with dtype float64, guaranteed unit norm (||v|| = 1.0).
        """
        # Fast path check for input
        text_segments = self._extract_history_text(history)

        if query is not None:
            clean_query = query.strip() if isinstance(query, str) else str(query).strip()
            if clean_query:
                text_segments.append(clean_query)

        if not text_segments:
            return self._fallback_vector.copy()

        combined_text = " ".join(text_segments)

        # TF-IDF sparse transform
        tfidf_vec = self._vectorizer.transform([combined_text])

        # If all tokens are unseen / zero-vector, return uniform fallback unit vector
        if tfidf_vec.nnz == 0:
            return self._fallback_vector.copy()

        # TruncatedSVD dimensionality reduction (16 components)
        feat_16d = self._svd.transform(tfidf_vec)[0].astype(np.float64)

        # Compute L2 norm
        norm = float(np.linalg.norm(feat_16d))

        # Check for numerical instability or zero vector
        if norm < 1e-12 or np.isnan(norm) or np.isinf(norm):
            return self._fallback_vector.copy()

        # Guaranteed unit norm
        unit_vector = feat_16d / norm
        return unit_vector


# Singleton instance for high-throughput zero-initialization inference
feature_extractor = ContextFeatureExtractor()
