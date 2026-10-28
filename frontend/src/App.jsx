/*
This handles the 
1.login screen
2.navigation
3.historical wastewater cost data
4.charts
5.machine-learning predictions
6.city comparisons.
*/

//useState lets components remember changing values.
//useEffect lets components perform tasks such as retrieving data from an API.
import { useState, useEffect } from "react";
import {
    LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
    ResponsiveContainer, ReferenceArea,
} from "recharts";

//this library has open-sourced icons free to use
import {
    Droplets, LayoutDashboard, Database, Home, Building2, TrendingUp, Cpu, Info,
    LogOut, Bell, Users, UserCheck, Search, Eye, EyeOff, ChevronDown,
    ChevronLeft, ChevronRight, UserCircle, X,
} from "lucide-react";

//apply index.css style to components
import "./index.css";

//establishing local host
const API = "http://127.0.0.1:8000";
const COLORS = ["#1769d1", "#43a047", "#f9a825", "#0b2a5b", "#e53935"];

//This defines a helper function for displaying money.
//If v is missing, display a dash. If money is present, convert it to a number and display it with two decimal places and a dollar sign.
const money = (v) => (v == null ? "—" : `$${Number(v).toFixed(2)}`);

const TARGETS = {
    res_fee_5k_gal: "Residential Fee (Per 5,000 Gal)",
    com_fee_50k_gal: "Commercial Fee (Per 50,000 Gal)",
};

//the three ML models sponsors want us to train
const MODEL_NAMES = {
    linear_regression: "Linear Regression",
    random_forest: "Random Forest",
    xgboost: "XGBoost Regression",
};

//This creates an array of years from 2017 through 2040.
const FULL_YEARS = Array.from({ length: 24 }, (_, i) => 2017 + i); // 2017..2040


async function get(path, token) {
    //fetch sends an http request
    //${API}${path} combines the base URL with the endpoint
    const res = await fetch(`${API}${path}`, {
        //makes sure that the user is logged in
        headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(res.status);
    return res.json();
}

/* ---------- these are helpers ---------- */

//CitySelect creates a dropdown for selecting a city. 
// It retrieves available cities from the backend and lets the parent component know which city the user selected.
function CitySelect({ token, value, onChange, group = "" }) {
    const [cities, setCities] = useState([]);
    useEffect(() => {
        get(`/api/city-list?group=${encodeURIComponent(group)}`, token).then((list) => {
            setCities(list);
            if (!list.includes(value)) onChange(list.includes("Houston") ? "Houston" : list[0]);
        });
        // eslint-disable-next-line
    }, [token, group]);
    return (
        <select value={value} onChange={(e) => onChange(e.target.value)}>
            {cities.map((c) => <option key={c}>{c}</option>)}
        </select>
    );
}
//This component creates the Add city dropdown used in the city comparison page.
function CityAdder({ token, onAdd }) {
    const [cities, setCities] = useState([]);

    //useEffect(...): fetches the city list when the component first appears or the token changes.
    //then(setCities): passes the response directly to setCities

    useEffect(() => { get("/api/city-list?group=", token).then(setCities); }, [token]);
    return (
        <select className="adder" value="" onChange={(e) => e.target.value && onAdd(e.target.value)}>
            <option value="">+ Add city</option>
            {cities.map((c) => <option key={c}>{c}</option>)}
        </select>
    );
}


//This helper prepares historical and predicted values so Recharts can display them on the same chart.
function buildSeries(f) {
    const map = {};
    //Loops through historical records. For each record h, it stores an object containing the year and actual value.
    f.history.forEach((h) => (map[h.year] = { year: h.year, actual: h.value }));
    f.predictions.forEach((p) => {
        map[p.year] = { ...(map[p.year] || { year: p.year }), predicted: p.value };
    });
    const last = f.history[f.history.length - 1];
    if (last && f.predictions.length) map[last.year].predicted = last.value;
    return Object.values(map).sort((a, b) => a.year - b.year);
}

const axisTick = { fontSize: 10, fill: "#556" };

/* ---------- Dashboard ---------- */

function Dashboard({ token }) {
    const [groups, setGroups] = useState([]);
    const [group, setGroup] = useState("");
    const [city, setCity] = useState("Houston");
    const [start, setStart] = useState(2017);
    const [history, setHistory] = useState([]);

    useEffect(() => { get("/api/groups", token).then(setGroups); }, [token]);

    //Run the effect whenever token changes or city changes.
    //uses the earlier defined get request
    useEffect(() => {
        if (city) get(`/api/cities/${encodeURIComponent(city)}/history`, token).then(setHistory);
    }, [token, city]);

    const rows = history.filter((r) => r.year >= start);
    const last = rows[rows.length - 1] || {};
    const pop = last.population ? `${(last.population / 1e6).toFixed(2)}M` : "—";

    const charts = [
        ["res_fee_5k_gal", "Residential Sewer Fee Trend (Per 5,000 Gallons)", "#2e9e4f", "Residential Fee"],
        ["com_fee_50k_gal", "Commercial Sewer Fee Trend (Per 50,000 Gallons)", "#1769d1", "Commercial Fee"],
    ];

    return (
        <>
            <div className="filters">
                <label>Select City <CitySelect token={token} value={city} onChange={setCity} group={group} /></label>
                <label>Year Range
                    <select value={start} onChange={(e) => setStart(Number(e.target.value))}>
                        {[2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024].map((y) =>
                            <option key={y} value={y}>{y} - 2025</option>)}
                    </select>
                </label>
                <label>Population Group
                    <select value={group} onChange={(e) => setGroup(e.target.value)}>
                        <option value="">All Groups</option>
                        {groups.map((g) => <option key={g}>{g}</option>)}
                    </select>
                </label>
            </div>

            <div className="kpis">
                <div className="kpi">
                    <div className="icon-tile tile-green"><Home size={28} /></div>
                    <div><div className="label">Residential Sewer Fee</div><div className="value">{money(last.res_fee_5k_gal)}</div><div className="sub">Per 5,000 Gallons</div></div>
                </div>
                <div className="kpi">
                    <div className="icon-tile tile-blue"><Building2 size={28} /></div>
                    <div><div className="label">Commercial Sewer Fee</div><div className="value">{money(last.com_fee_50k_gal)}</div><div className="sub">Per 50,000 Gallons</div></div>
                </div>
                <div className="kpi">
                    <div className="icon-tile tile-purple"><Users size={28} /></div>
                    <div><div className="label">City Population</div><div className="value">{pop}</div><div className="sub">Population</div></div>
                </div>
                <div className="kpi">
                    <div className="icon-tile tile-orange"><UserCheck size={28} /></div>
                    <div><div className="label">Total Customers</div><div className="value">{last.total_customers?.toLocaleString() ?? "—"}</div><div className="sub">Customers</div></div>
                </div>
            </div>

            <div className="chart-row">
                {charts.map(([key, title, color, name]) => (
                    <div className="content-box" key={key}>
                        <h3 className="chart-title">{title}</h3>
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={rows} margin={{ top: 22, right: 20, left: 0, bottom: 0 }}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e3e8ef" />
                                <XAxis dataKey="year" tick={axisTick} />
                                <YAxis tick={axisTick} tickFormatter={(v) => `$${v}`} />
                                <Tooltip formatter={(v) => money(v)} />
                                <Line
                                    dataKey={key} name={name} stroke={color} strokeWidth={2} connectNulls
                                    dot={{ r: 3, fill: color }}
                                    label={{ position: "top", fontSize: 9, fill: "#445", formatter: (v) => money(v) }}
                                />
                                <Legend verticalAlign="bottom" />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                ))}
            </div>
        </>
    );
}

/* ---------- Historical Data ---------- */

function HistoricalData({ token }) {
    const [all, setAll] = useState([]);
    const [years, setYears] = useState([]);
    const [groups, setGroups] = useState([]);
    const [search, setSearch] = useState("");
    const [year, setYear] = useState("");
    const [group, setGroup] = useState("");
    const [pageNo, setPageNo] = useState(0);
    const PER = 10;

    useEffect(() => {
        get("/api/groups", token).then(setGroups);
        get("/api/years", token).then(async (ys) => {
            setYears(ys);
            const parts = await Promise.all(ys.map((y) =>
                get(`/api/costs?year=${y}`, token).then((r) => r.map((x) => ({ ...x, year: y })))));
            setAll(parts.flat().sort((a, b) => a.city.localeCompare(b.city) || a.year - b.year));
        });
    }, [token]);

    const filtered = all.filter((r) =>
        (!year || r.year === Number(year)) &&
        (!group || r.population_group === group) &&
        r.city.toLowerCase().includes(search.toLowerCase()));
    const pages = Math.max(1, Math.ceil(filtered.length / PER));
    const shown = filtered.slice(pageNo * PER, pageNo * PER + PER);
    const nums = [];
    for (let i = Math.max(0, pageNo - 2); i <= Math.min(pages - 1, pageNo + 2); i++) nums.push(i);
//allows users to download historical data table as csv file
    function downloadCsv() {
        const head = "city,year,population_group,population,total_customers,res_fee_5k_gal,com_fee_50k_gal";
        const lines = filtered.map((r) =>
            [`"${r.city}"`, r.year, `"${r.population_group}"`, r.population, r.total_customers,
             r.res_fee_5k_gal ?? "", r.com_fee_50k_gal ?? ""].join(","));
        const blob = new Blob([[head, ...lines].join("\n")], { type: "text/csv" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "wastewater_costs.csv";
        a.click();
    }

    return (
        <div className="content-box">
            <h2 className="card-title">Historical Wastewater Cost Data</h2>
            <div className="filters">
                <label>Search City
                    <span className="search-wrap">
                        <input value={search} placeholder="Search city..."
                            onChange={(e) => { setSearch(e.target.value); setPageNo(0); }} />
                        <Search size={16} />
                    </span>
                </label>
                <label>Year
                    <select value={year} onChange={(e) => { setYear(e.target.value); setPageNo(0); }}>
                        <option value="">All Years</option>
                        {years.map((y) => <option key={y}>{y}</option>)}
                    </select>
                </label>
                <label>Population Group
                    <select value={group} onChange={(e) => { setGroup(e.target.value); setPageNo(0); }}>
                        <option value="">All Groups</option>
                        {groups.map((g) => <option key={g}>{g}</option>)}
                    </select>
                </label>
                <button className="btn" onClick={downloadCsv}>Download CSV</button>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>City</th><th>Year</th><th>Population</th><th>Total Customers</th>
                        <th>Population Group</th><th>Residential Fee (Per 5,000 Gal)</th><th>Commercial Fee (Per 50,000 Gal)</th>
                    </tr>
                </thead>
                <tbody>
                    {shown.map((r) => (
                        <tr key={`${r.city}-${r.year}`}>
                            <td>{r.city}</td><td>{r.year}</td><td>{r.population?.toLocaleString()}</td>
                            <td>{r.total_customers?.toLocaleString()}</td><td>{r.population_group}</td>
                            <td>{money(r.res_fee_5k_gal)}</td><td>{money(r.com_fee_50k_gal)}</td>
                        </tr>
                    ))}
                </tbody>
            </table>

            <div className="pager">
                <span>Showing {filtered.length ? pageNo * PER + 1 : 0} to {Math.min((pageNo + 1) * PER, filtered.length)} of {filtered.length} entries</span>
                <div className="pager-btns">
                    <button className="pg" disabled={pageNo === 0} onClick={() => setPageNo(pageNo - 1)}><ChevronLeft size={14} /></button>
                    {nums.map((n) => (
                        <button key={n} className={`pg ${n === pageNo ? "active" : ""}`} onClick={() => setPageNo(n)}>{n + 1}</button>
                    ))}
                    <button className="pg" disabled={pageNo >= pages - 1} onClick={() => setPageNo(pageNo + 1)}><ChevronRight size={14} /></button>
                </div>
            </div>
        </div>
    );
}

/* ---------- Residential / Commercial Prediction ---------- */

function Prediction({ token, target }) {
    const [city, setCity] = useState("Houston");
    const [data, setData] = useState(null);
    const [models, setModels] = useState([]);
    const isRes = target === "res_fee_5k_gal";
    const color = isRes ? "#2e9e4f" : "#1769d1";

    //once ML machine prediction is loaded into prediction table generate it here
    function generate() {
        get(`/api/cities/${encodeURIComponent(city)}/forecast?target=${target}`, token).then(setData);
    }
    useEffect(() => { get("/api/models", token).then(setModels); }, [token]);
    useEffect(() => { if (city) generate(); /* eslint-disable-next-line */ }, [city, target]);

    const series = data ? buildSeries(data) : [];
    const lastActual = data?.history[data.history.length - 1];
    const predAt = (y) => data?.predictions.find((p) => p.year === y)?.value;
    const p2040 = predAt(2040);
    const change = lastActual && p2040 ? ((p2040 - lastActual.value) / lastActual.value) * 100 : null;
    const model = models.find((m) => m.target === target && m.is_deployed);
    const splitYear = lastActual?.year ?? 2025;

    return (
        <div className="content-box">
            <h2 className="card-title">
                {isRes ? "Residential" : "Commercial"} Sewer Fee Prediction (Per {isRes ? "5,000" : "50,000"} Gallons)
            </h2>
            <div className="filters">
                <label>Select City <CitySelect token={token} value={city} onChange={setCity} /></label>
                <label>Predict For <select><option>Next 15 Years (2026 - 2040)</option></select></label>
                <button className={`btn ${isRes ? "green" : ""}`} onClick={generate}>Generate Prediction</button>
            </div>

            {data && data.predictions.length === 0 && (
                <div className="notice">No predictions are loaded yet. Run the ML script, then load its CSV with load_predictions.py.</div>
            )}

            <div className="pred-grid">
                <div>
                    <ResponsiveContainer width="100%" height={320}>
                        <LineChart data={series} margin={{ top: 24, right: 16, left: 0, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e3e8ef" />
                            <XAxis dataKey="year" type="number" domain={[2017, 2040]} ticks={FULL_YEARS} tick={axisTick} interval={0} />
                            <YAxis tick={axisTick} tickFormatter={(v) => `$${v}`} />
                            <Tooltip formatter={(v) => money(v)} />
                            <ReferenceArea x1={2017} x2={splitYear} fillOpacity={0}
                                label={{ value: "Historical (2017 - 2025)", position: "insideTop", fontSize: 12, fill: "#223" }} />
                            <ReferenceArea x1={splitYear} x2={2040} fill="#dbe9fb" fillOpacity={0.6}
                                label={{ value: "Predicted (2026 - 2040)", position: "insideTop", fontSize: 12, fill: "#223" }} />
                            <Line dataKey="actual" name="Actual Fee" stroke={color} strokeWidth={2} dot={{ r: 3, fill: color }} connectNulls />
                            <Line dataKey="predicted" name="Predicted Fee" stroke={color} strokeWidth={2}
                                strokeDasharray="2 4" dot={{ r: 3, fill: color }} connectNulls />
                            <Legend verticalAlign="bottom" />
                        </LineChart>
                    </ResponsiveContainer>

                    <div className="model-strip">
                        <span>Selected Model<b>{MODEL_NAMES[model?.model_name] ?? model?.model_name ?? "—"}</b></span>
                        <span>R² Score<b>{model?.r2?.toFixed(2) ?? "—"}</b></span>
                        <span>MAE<b>{model?.mae?.toFixed(2) ?? "—"}</b></span>
                        <span>RMSE<b>{model?.rmse?.toFixed(2) ?? "—"}</b></span>
                    </div>
                </div>

                <div className="summary-card">
                    <h3>Prediction Summary</h3>
                    <div className="summary-row"><span>{lastActual?.year ?? 2025} Actual Fee</span><b>{money(lastActual?.value)}</b></div>
                    <div className="summary-row"><span>2030 Predicted Fee</span><b>{money(predAt(2030))}</b></div>
                    <div className="summary-row"><span>2035 Predicted Fee</span><b>{money(predAt(2035))}</b></div>
                    <div className="summary-row"><span>2040 Predicted Fee</span><b>{money(p2040)}</b></div>
                    <div className="summary-row">
                        <span>Expected Change<br />({lastActual?.year ?? 2025}-2040)</span>
                        <b className="good">{change == null ? "—" : `${change.toFixed(2)}%`}</b>
                    </div>
                </div>
            </div>
        </div>
    );
}

/* ---------- City Comparison ---------- */

function CityComparison({ token }) {
    const [target, setTarget] = useState("res_fee_5k_gal");
    const [selected, setSelected] = useState(["Houston", "McKinney", "Mesquite", "Pasadena", "McAllen"]);
    const [results, setResults] = useState([]);

    function compare() {
        if (!selected.length) { setResults([]); return; }
        get(`/api/compare?cities=${encodeURIComponent(selected.join(","))}&target=${target}`, token).then(setResults);
    }
    useEffect(() => { compare(); /* eslint-disable-next-line */ }, []);

    const merged = {};
    results.forEach((r) => {
        [...r.history, ...r.predictions].forEach((p) => {
            merged[p.year] = { ...(merged[p.year] || { year: p.year }), [r.city]: p.value };
        });
    });
    const series = Object.values(merged).sort((a, b) => a.year - b.year);

    const stats = results.filter((r) => r.history.length > 1).map((r) => {
        const first = r.history[0], last = r.history[r.history.length - 1];
        const span = Math.max(1, last.year - first.year);
        return { city: r.city, last: last.value, growth: (Math.pow(last.value / first.value, 1 / span) - 1) * 100 };
    });
    const lowest = stats.reduce((a, b) => (b.last < a.last ? b : a), stats[0] || {});
    const highest = stats.reduce((a, b) => (b.last > a.last ? b : a), stats[0] || {});
    const fastest = stats.reduce((a, b) => (b.growth > a.growth ? b : a), stats[0] || {});
    const avg = stats.length ? stats.reduce((s, x) => s + x.last, 0) / stats.length : null;

    return (
        <div className="content-box">
            <div className="filters">
                <label>Select Metric
                    <select value={target} onChange={(e) => setTarget(e.target.value)}>
                        {Object.entries(TARGETS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                </label>
                <label>Compare Cities
                    <div className="chip-box">
                        {selected.map((c) => (
                            <span className="chip" key={c}>{c}
                                <button onClick={() => setSelected(selected.filter((x) => x !== c))}><X size={12} /></button>
                            </span>
                        ))}
                        <CityAdder token={token} onAdd={(c) => !selected.includes(c) && setSelected([...selected, c])} />
                    </div>
                </label>
                <button className="btn" onClick={compare}>Compare</button>
            </div>

            <div className="pred-grid">
                <ResponsiveContainer width="100%" height={340}>
                    <LineChart data={series} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e3e8ef" />
                        <XAxis dataKey="year" type="number" domain={[2017, 2040]} ticks={FULL_YEARS} tick={axisTick} interval={0} />
                        <YAxis tick={axisTick} tickFormatter={(v) => `$${v}`} />
                        <Tooltip formatter={(v) => money(v)} />
                        <Legend verticalAlign="top" />
                        {results.map((r, i) => (
                            <Line key={r.city} dataKey={r.city} stroke={COLORS[i % COLORS.length]}
                                strokeWidth={2} connectNulls dot={false} />
                        ))}
                    </LineChart>
                </ResponsiveContainer>

                <div className="summary-card">
                    <h3>Comparison Insights</h3>
                    <div className="summary-row"><span>Lowest Cost<br />(2025)</span><b>{lowest?.city}<br />({money(lowest?.last)})</b></div>
                    <div className="summary-row"><span>Highest Cost<br />(2025)</span><b>{highest?.city}<br />({money(highest?.last)})</b></div>
                    <div className="summary-row"><span>Fastest Growing<br />Cost</span><b>{fastest?.city}<br />({fastest?.growth?.toFixed(2)}%/yr)</b></div>
                    <div className="summary-row"><span>Average Fee<br />(selected)</span><b>{money(avg)}</b></div>
                </div>
            </div>
        </div>
    );
}

/* ---------- ML Model Performance / About ---------- */

function ModelPerformance({ token }) {
    const [models, setModels] = useState([]);
    useEffect(() => { get("/api/models", token).then(setModels); }, [token]);
    return (
        <div className="content-box">
            <h2 className="card-title">Model Comparison</h2>
            {models.length === 0 && <div className="notice">No models recorded yet. The training script should insert rows into model_metadata.</div>}
            <table>
                <thead><tr><th>Model</th><th>Target</th><th>R²</th><th>MAE</th><th>RMSE</th><th>Deployed</th></tr></thead>
                <tbody>
                    {models.map((m, i) => (
                        <tr key={i}>
                            <td>{MODEL_NAMES[m.model_name] ?? m.model_name}</td><td>{TARGETS[m.target]}</td>
                            <td>{m.r2?.toFixed(3)}</td><td>{m.mae?.toFixed(2)}</td><td>{m.rmse?.toFixed(2)}</td>
                            <td>{m.is_deployed ? "✔" : ""}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function About() {
    return (
        <div className="content-box">
            <h2 className="card-title">About</h2>
            <p>Machine learning web application that analyzes Texas wastewater costs (2017–2025) and predicts residential and commercial sewer fees for the next 15 years.</p>
            <p>CSE 496 Capstone Project </p>
            <p>In collaboration with Brown &amp; Caldwell / University of Louisville.</p>
        </div>
    );
}

/* ---------- App shell ---------- */

const NAV = [
    ["Dashboard", LayoutDashboard],
    ["Historical Data", Database],
    ["Residential Prediction", Home],
    ["Commercial Prediction", Building2],
    ["City Comparison", TrendingUp],
    ["ML Model Performance", Cpu],
    ["About", Info],
];

function App() {
    const [token, setToken] = useState(null);
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [showPw, setShowPw] = useState(false);
    const [error, setError] = useState("");
    const [page, setPage] = useState("Dashboard");

    //handles login
    //fetch sends a POST request to the backend with the username and password. 
    // If successful, it stores the access token in state and clears the password field.
    //  If unsuccessful, it sets an error message.
    async function handleLogin() {
        setError("");
        try {
            const res = await fetch(`${API}/login`, {
                method: "POST", 
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password }),
            });
            const data = await res.json();
            if (!res.ok) { setError(data.detail || "Login failed"); return; }
            setToken(data.access_token);
            setPassword("");
        } catch {
            setError("Can't reach the server. Check if uvicorn running.");
        }
    }
    //if token is not present, display the login page. 
    // Otherwise, display the main application with navigation and content.
    if (!token) {
        return (
            <div className="login-page" style={{ backgroundImage: "url(/login_background.png)" }}>
                <div className="login-box">
                    <div className="login-logo">
                        <Droplets size={56} color="#1769d1" strokeWidth={1.8} />
                        <div>
                            <div className="brand-top">TEXAS</div>
                            <div className="brand-sub">WASTEWATER COST<br />PREDICTION SYSTEM</div>
                        </div>
                    </div>
                    <p className="tagline">Machine Learning Based Analytics</p>

                    <label className="field">Email / Username</label>
                    <input type="text" placeholder="Enter your email or username"
                        value={username} onChange={(e) => setUsername(e.target.value)} />

                    <label className="field">Password</label>
                    <div className="pw-wrap">
                        <input type={showPw ? "text" : "password"} placeholder="Enter your password"
                            value={password} onChange={(e) => setPassword(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && handleLogin()} />
                        <button type="button" onClick={() => setShowPw(!showPw)}>
                            {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
                        </button>
                    </div>

                    <div className="login-options">
                        <label><input type="checkbox" /> Remember me</label>
                        <a href="#">Forgot password?</a>
                    </div>

                    {error && <p className="login-error">{error}</p>}
                    <button className="login-btn" onClick={handleLogin}>LOGIN</button>
                    <div className="login-foot">Wastewater Cost Analysis | 2017 – 2025</div>
                </div>
            </div>
        );
    }

    const isPrediction = page.endsWith("Prediction");

    return (
        <div>
            <header className="top-bar">
                <div className="top-title"><Droplets size={26} color="#4aa3ff" /> Texas Wastewater Cost Prediction System</div>
                <div className="top-right">
                    <span className="bell"><Bell size={18} /></span>
                    <span className="admin"><UserCircle size={26} /> Administrator <ChevronDown size={14} /></span>
                </div>
            </header>

            <aside className="sidebar">
                {NAV.map(([name, Icon]) => (
                    <button key={name} className={page === name ? "active" : ""} onClick={() => setPage(name)}>
                        <Icon size={18} /> {name}
                    </button>
                ))}
                <div className="spacer" />
                <button className="logout" onClick={() => setToken(null)}><LogOut size={18} /> Logout</button>
            </aside>

            <main className="dashboard-content">
                {!isPrediction && <h1>{page}</h1>}
                {page === "Dashboard" && <Dashboard token={token} />}
                {page === "Historical Data" && <HistoricalData token={token} />}
                {page === "Residential Prediction" && <Prediction token={token} target="res_fee_5k_gal" />}
                {page === "Commercial Prediction" && <Prediction token={token} target="com_fee_50k_gal" />}
                {page === "City Comparison" && <CityComparison token={token} />}
                {page === "ML Model Performance" && <ModelPerformance token={token} />}
                {page === "About" && <About />}
            </main>
        </div>
    );
}

export default App;