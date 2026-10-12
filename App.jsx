import { useState } from "react";
import "./index.css";

function App() {
    const [loggedIn, setLoggedIn] = useState(false);
    const [page, setPage] = useState("Dashboard");

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
                    />

                    <label>Password</label>
                    <input
                        type="password"
                        placeholder="Enter your password"
                    />

                    <div className="login-options">
                        <label>
                            <input type="checkbox" />
                            Remember me
                        </label>

                        <a href="#">Forgot password?</a>
                    </div>

                    <button onClick={() => setLoggedIn(true)}>
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
                    onClick={() => setLoggedIn(false)}
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

                        <p>
                            Texas Wastewater Cost Prediction System
                        </p>

                        <p>
                            Use the navigation menu to explore the system.
                        </p>

                    </div>
                )}

                {page === "Historical Data" && (
                    <div className="content-box">
                        <h2>Historical Data</h2>
                    </div>
                )}

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