import { useState, useEffect } from "react";
import "./index.css";

const API = "http://127.0.0.1:8000";

function HistoricalData({ token }) {
    const [years, setYears] = useState([]);
    const [year, setYear] = useState(2025);
    const [rows, setRows] = useState([]);

    useEffect(() => {
        const headers = { Authorization: `Bearer ${token}` };
        fetch(`${API}/api/years`, { headers })
            .then((r) => r.json())
            .then(setYears);
    }, [token]);

    useEffect(() => {
        const headers = { Authorization: `Bearer ${token}` };
        fetch(`${API}/api/costs?year=${year}`, { headers })
            .then((r) => r.json())
            .then(setRows);
    }, [token, year]);

    const money = (v) => (v == null ? "—" : `$${v.toFixed(2)}`);

    return (
        <div className="content-box">
            <h2>Historical Data</h2>

            <label>
                Year:{" "}
                <select
                    value={year}
                    onChange={(e) => setYear(Number(e.target.value))}
                >
                    {years.map((y) => (
                        <option key={y} value={y}>{y}</option>
                    ))}
                </select>
            </label>

            <p>{rows.length} cities reported</p>

            <table>
                <thead>
                    <tr>
                        <th>City</th>
                        <th>Population</th>
                        <th>Customers</th>
                        <th>Residential (5k gal)</th>
                        <th>Commercial (50k gal)</th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map((r) => (
                        <tr key={r.city}>
                            <td>{r.city}</td>
                            <td>{r.population?.toLocaleString()}</td>
                            <td>{r.total_customers?.toLocaleString()}</td>
                            <td>{money(r.res_fee_5k_gal)}</td>
                            <td>{money(r.com_fee_50k_gal)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function App() {
    const [token, setToken] = useState(null);
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [page, setPage] = useState("Dashboard");

    const loggedIn = token !== null;

    async function handleLogin() {
        setError("");
        try {
            const res = await fetch(`${API}/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password }),
            });
            const data = await res.json();
            if (!res.ok) {
                setError(data.detail || "Login failed");
                return;
            }
            setToken(data.access_token);
            setPassword("");
        } catch {
            setError("Cannot reach the server. Is uvicorn running?");
        }
    }

    if (!loggedIn) {
        return (
            <div className="login-page">
                <div className="login-box">

                    <h1>Texas Wastewater</h1>
                    <h2>Cost Prediction System</h2>

                    <label>Email / Username</label>
                    <input
                        type="text"
                        placeholder="Enter your email or username"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                    />

                    <label>Password</label>
                    <input
                        type="password"
                        placeholder="Enter your password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                    />

                    <div className="login-options">
                        <label>
                            <input type="checkbox" />
                            Remember me
                        </label>

                        <a href="#">Forgot password?</a>
                    </div>

                    {error && <p style={{ color: "crimson" }}>{error}</p>}

                    <button onClick={handleLogin}>
                        Login
                    </button>

                </div>
            </div>
        );
    }

    return (
        <div className="dashboard">

            <header className="top-bar">
                <h2>Texas Wastewater Cost Prediction System</h2>

                <button
                    className="logout-button"
                    onClick={() => setToken(null)}
                >
                    Logout
                </button>
            </header>

            <aside className="sidebar">

                <h3>Navigation</h3>

                <button onClick={() => setPage("Dashboard")}>
                    Dashboard
                </button>

                <button onClick={() => setPage("Historical Data")}>
                    Historical Data
                </button>

                <button onClick={() => setPage("Residential Prediction")}>
                    Residential Prediction
                </button>

                <button onClick={() => setPage("Commercial Prediction")}>
                    Commercial Prediction
                </button>

                <button onClick={() => setPage("City Comparison")}>
                    City Comparison
                </button>

                <button onClick={() => setPage("ML Model Performance")}>
                    ML Model Performance
                </button>

                <button onClick={() => setPage("About")}>
                    About
                </button>

            </aside>

            <main className="dashboard-content">

                <h1>{page}</h1>

                {page === "Dashboard" && (
                    <div className="content-box">
                        <h2>Welcome</h2>
                        <p>Texas Wastewater Cost Prediction System</p>
                        <p>Use the navigation menu to explore the system.</p>
                    </div>
                )}

                {page === "Historical Data" && <HistoricalData token={token} />}

                {page === "Residential Prediction" && (
                    <div className="content-box">
                        <h2>Residential Prediction</h2>
                    </div>
                )}

                {page === "Commercial Prediction" && (
                    <div className="content-box">
                        <h2>Commercial Prediction</h2>
                    </div>
                )}

                {page === "City Comparison" && (
                    <div className="content-box">
                        <h2>City Comparison</h2>
                    </div>
                )}

                {page === "ML Model Performance" && (
                    <div className="content-box">
                        <h2>ML Model Performance</h2>
                    </div>
                )}

                {page === "About" && (
                    <div className="content-box">
                        <h2>About</h2>
                    </div>
                )}

            </main>

        </div>
    );
}

export default App;