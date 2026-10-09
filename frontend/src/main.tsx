import { StrictMode, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import "./plain-language.css";
import "./error-states.css";
import "./search-suggestions.css";
import "./glance.css";

type SourceData = { source_url: string; source_quote: string; source_title?: string | null };
type Finding = { value: string; source: SourceData; evidence_type: string; outcome?: string | null; population?: string | null; follow_up?: string | null; comparator?: string | null };
type Treatment = { treatment_name: string; label_name: string; label_url: string; description?: string; common_side_effects: string[]; common_side_effects_source?: SourceData | null; efficacy?: Finding | null; discontinuation_rate?: Finding | null; boxed_warning?: Finding | null; boxed_warning_status: string; published_trial_evidence: Finding[]; issues: string[]; faers_frequently_reported_reactions: string[]; faers_source_url?: string | null };
type Failed = { error: string };
type Overview = { plain_language_summary: string; common_symptoms: string[]; causes_or_risk_factors: string[]; source?: SourceData | null };
type Standard = { treatment_name: string; description: string; efficacy?: Finding | null; efficacy_treatment_name?: string | null; guideline_name: string; guideline_source: SourceData; prescribing_volume_status: string; issues: string[] };
type Treatments = { treatments: Treatment[]; issues: string[] };
type Trial = { title: string; brief_summary: string; phase: string; enrollment: number; location: string; study_url: string };
type Page = { disease: string; partial: boolean; overview: Overview | Failed; standard_of_care: Standard | Failed; label_safety: Treatments | Failed; alternative_treatments: Treatments | Failed; trials: { trials: Trial[] } | Failed };

const sections = ["At a glance", "Overview", "Standard of care", "Safety of standard treatment", "Other common treatments", "Questions for your Doctor", "Clinical trials"];
const diseaseSuggestions = ["Rheumatoid arthritis", "Type 2 diabetes", "Alzheimer’s disease", "Rett syndrome", "Asthma", "Parkinson’s disease", "Crohn’s disease", "Lupus"];
const sectionId = (title: string) => title.toLowerCase().replace(/ /g, "-");

function CompassMark({ small = false }: { small?: boolean }) {
  return <svg className={small ? "compass-mark small" : "compass-mark"} viewBox="0 0 48 48" role="img" aria-label="Clinical Compass">
    <circle cx="24" cy="24" r="20" fill="none" stroke="currentColor" strokeWidth="2.5" />
    <path d="m31 16-5 12-10 5 5-12 10-5Z" fill="currentColor" />
    <circle cx="24" cy="24" r="2" fill="white" />
  </svg>;
}

function ConditionIllustration({ disease }: { disease: string }) {
  const name = disease.toLowerCase();
  const type = /arthritis|joint|gout/.test(name) ? "joints"
    : /alzheimer|dementia|parkinson|epilepsy/.test(name) ? "brain"
    : /diabetes/.test(name) ? "glucose"
    : /asthma|copd|pulmonary|lung/.test(name) ? "lungs"
    : /heart|cardiac|cardiovascular/.test(name) ? "heart" : "whole-person";
  const labels: Record<string, string> = {
    joints: "Joints & movement", brain: "Brain & memory", glucose: "Blood sugar",
    lungs: "Lungs & breathing", heart: "Heart & circulation", "whole-person": "Your whole health",
  };
  return <aside className={`condition-art art-${type}`} aria-label={`Illustration: ${labels[type]}`}>
    <span className="art-caption">A SIMPLE PICTURE</span>
    <svg viewBox="0 0 128 104" role="img" aria-hidden="true">
      <circle className="art-halo" cx="64" cy="52" r="43" />
      {type === "joints" && <g className="art-drawing"><path d="M39 22 52 44 46 68 34 82M89 22 76 44 82 68 94 82"/><path d="m52 44 12 8 12-8M46 68l18-16 18 16"/><circle className="art-point" cx="52" cy="44" r="5"/><circle className="art-point" cx="76" cy="44" r="5"/><circle className="art-point" cx="46" cy="68" r="5"/><circle className="art-point" cx="82" cy="68" r="5"/></g>}
      {type === "brain" && <g className="art-drawing"><path d="M63 23c-9-12-25-3-22 9-10 0-12 15-4 19-6 10 1 19 11 18 4 12 16 9 18 2V32c0-4-1-7-3-9Zm3 0c9-12 25-3 22 9 10 0 12 15 4 19 6 10-1 19-11 18-4 12-16 9-18 2V32c0-4 1-7 3-9Z"/><path d="M49 35c8 1 9 8 6 13m-10 8c8-1 12 4 11 11m23-32c-8 1-9 8-6 13m10 8c-8-1-12 4-11 11"/><circle className="art-point" cx="64" cy="54" r="3"/></g>}
      {type === "glucose" && <g className="art-drawing"><path d="M42 28c13 7 31 7 44 0M39 50c15 8 35 8 50 0M42 73c13-7 31-7 44 0"/><circle className="art-point" cx="48" cy="29" r="4"/><circle className="art-point" cx="78" cy="50" r="4"/><circle className="art-point" cx="57" cy="72" r="4"/><circle cx="68" cy="29" r="3"/><circle cx="54" cy="50" r="3"/><circle cx="74" cy="73" r="3"/></g>}
      {type === "lungs" && <g className="art-drawing"><path d="M64 22v30m0-14-11 10m11-10 11 10"/><path d="M53 45c-9-9-22 4-24 19-3 15 8 19 20 14 10-4 14-15 15-26m11-7c9-9 22 4 24 19 3 15-8 19-20 14-10-4-14-15-15-26"/><circle className="art-point" cx="43" cy="62" r="4"/><circle className="art-point" cx="85" cy="62" r="4"/></g>}
      {type === "heart" && <g className="art-drawing"><path d="M64 79 35 53C17 34 43 18 58 36l6 8 6-8c15-18 41-2 23 17L64 79Z"/><path d="M30 55h17l8-14 12 27 9-15h23"/><circle className="art-point" cx="64" cy="68" r="3"/></g>}
      {type === "whole-person" && <g className="art-drawing"><circle cx="64" cy="34" r="12"/><path d="M42 83c2-19 9-29 22-29s20 10 22 29M49 62l-13 18m43-18 13 18"/><circle className="art-point" cx="64" cy="64" r="4"/></g>}
    </svg>
    <strong>{labels[type]}</strong><span className="art-footnote">Illustration for orientation</span>
  </aside>;
}

function glanceText(disease: string, summary: string) {
  const name = disease.toLowerCase();
  if (name.includes("rett")) return "A rare condition that changes how the brain develops. It can affect movement, talking, and everyday skills.";
  if (name.includes("arthritis")) return "A condition that can make joints sore, stiff, or swollen, making movement harder.";
  if (name.includes("diabetes")) return "A condition where the body has trouble keeping blood sugar at a healthy level.";
  if (name.includes("alzheimer") || name.includes("dementia")) return "A brain condition that can slowly affect memory, thinking, and everyday activities.";
  if (name.includes("asthma")) return "A condition that can make the airways narrow, causing coughing, wheezing, or trouble breathing.";
  const words = summary.trim().split(/\s+/).slice(0, 20).join(" ");
  return words ? `${words}${summary.trim().split(/\s+/).length > 20 ? "…" : ""}` : "A health condition that can affect how your body works.";
}

function Source({ source }: { source?: SourceData | null }) {
  if (!source) return null;
  return <details className="citation"><summary>Source &amp; exact quote</summary>
    <a href={source.source_url} target="_blank" rel="noreferrer">{source.source_title || "Open original source"} ↗</a>
    <blockquote>{source.source_quote}</blockquote>
  </details>;
}

function Preview({ text, words = 32 }: { text: string; words?: number }) {
  const parts = text.trim().split(/\s+/);
  if (parts.length <= words) return <p>{text}</p>;
  return <><p>{parts.slice(0, words).join(" ")}…</p><details className="read-more"><summary>Read the full explanation</summary><p>{text}</p></details></>;
}

function Evidence({ finding, empty }: { finding?: Finding | null; empty: string }) {
  if (!finding) return <p className="muted evidence-empty">{empty}</p>;
  const context = [["Outcome", finding.outcome], ["Study group", finding.population], ["Follow-up", finding.follow_up], ["Compared with", finding.comparator]].filter((entry): entry is [string, string] => Boolean(entry[1]));
  return <div className="evidence">
    <div className="evidence-top"><span className="badge">{finding.evidence_type}</span><span className="evidence-label">Study finding</span></div>
    <p className="finding-value">{finding.value}</p>
    {context.length > 0 && <dl className="evidence-context">{context.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
    <Source source={finding.source} />
  </div>;
}

function Issues({ issues = [] }: { issues?: string[] }) {
  return issues.length > 0 && <div className="section-note" role="status">{[...new Set(issues)].map(issue => <p key={issue}>{issue}</p>)}</div>;
}

function HelpfulError({ section, detail }: { section: string; detail: string }) {
  const treatmentSection = section === "Standard of care" || section === "Safety of standard treatment" || section === "Other common treatments";
  const message = treatmentSection
    ? "We found information about this disease, but not enough reliable treatment guidance to summarize safely. Try another spelling or discuss the condition with a specialist."
    : section === "Overview"
      ? "We found the disease name, but not enough reliable plain-language information to explain it safely. Try another spelling or discuss it with a healthcare professional."
      : "We couldn't retrieve enough reliable information for this section right now. Please try again or use the linked public sources when available.";
  return <div className="helpful-error" role="status"><strong>{message}</strong><details><summary>Why this section is unavailable</summary><p>{detail}</p></details></div>;
}

function PlainLanguageKey() {
  return <details className="plain-language-key">
    <summary>Medical terms, in everyday language</summary>
    <dl>
      <div><dt>Benefit in studies</dt><dd>How well the treatment helped people in a research study.</dd></div>
      <div><dt>Stopped because of side effects</dt><dd>How often people had to stop taking it because it caused problems.</dd></div>
      <div><dt>Boxed warning</dt><dd>The FDA’s strongest warning about a serious safety concern.</dd></div>
      <div><dt>FDA event reports</dt><dd>Reports people or health professionals sent to the FDA. They do not prove that a medicine caused a problem or show how often it happens.</dd></div>
    </dl>
  </details>;
}

function Section<T extends object>({ title, step, value, children }: { title: string; step: string; value: T | Failed; children: (data: T) => ReactNode }) {
  return <section className="card content-section" id={sectionId(title)}>
    <div className="section-heading"><span className="step-number">{step}</span><h2>{title}</h2></div>
    {'error' in value ? <HelpfulError section={title} detail={value.error} /> : children(value)}
  </section>;
}

function TreatmentCard({ treatment: t }: { treatment: Treatment }) {
  const moreEffects = t.common_side_effects.slice(7);
  return <article className="treatment">
    <div className="treatment-heading"><span className="treatment-symbol" aria-hidden="true">✳</span><div><h3>{t.treatment_name}</h3><a className="label-link" href={t.label_url} target="_blank" rel="noreferrer">FDA label: {t.label_name} ↗</a></div></div>
    {t.description && <div className="treatment-purpose"><span className="mini-label">WHAT IT IS USED FOR</span><Preview text={t.description} words={30} /></div>}
    <div className="treatment-grid">
      <div className="safety-block"><h4>Common side effects</h4>
        {t.common_side_effects.length ? <><ul className="effect-chips">{t.common_side_effects.slice(0, 7).map(effect => <li key={effect}>{effect}</li>)}</ul>{moreEffects.length > 0 && <details className="read-more"><summary>See {moreEffects.length} more</summary><ul className="effect-chips">{moreEffects.map(effect => <li key={effect}>{effect}</li>)}</ul></details>}<Source source={t.common_side_effects_source} /></> : <p className="muted">Could not verify side effects from the sources retrieved.</p>}
      </div>
      <div className="safety-block"><h4>Stopped because of side effects</h4><Evidence finding={t.discontinuation_rate} empty="No verified rate found in the retrieved label or studies." /></div>
    </div>
    <div className="benefit-block"><h4>What studies found</h4><p className="plain-label">This is the treatment’s measured benefit in research—not a promise of what will happen for one person.</p><Evidence finding={t.efficacy} empty="No disease-specific benefit was verified in the studies retrieved." /></div>
    {t.published_trial_evidence.length > 0 && <details className="more-evidence"><summary>More published safety findings ({t.published_trial_evidence.length})</summary>{t.published_trial_evidence.map((e, i) => <Evidence key={i} finding={e} empty="" />)}</details>}
    {t.boxed_warning ? <div className="warning"><span className="warning-icon" aria-hidden="true">!</span><div><strong>FDA boxed warning</strong><p>This label has a boxed warning. Read the details and discuss what they mean for you with your doctor.</p><details><summary>Read the warning from the label</summary><p className="warning-copy">{t.boxed_warning.value}</p><Source source={t.boxed_warning.source} /></details></div></div> : <p className="warning-status">{t.boxed_warning_status === "not_in_selected_label" ? "No boxed warning in the selected label. Other warnings may still apply." : "Boxed-warning status could not be verified."}</p>}
    {t.faers_frequently_reported_reactions.length > 0 && <details className="more-evidence"><summary>FDA event reports ({t.faers_frequently_reported_reactions.length})</summary><p className="muted">Voluntary reports do not show how often a side effect happens or prove the drug caused it.</p><p>{t.faers_frequently_reported_reactions.map(r => r.toLowerCase()).join(" · ")}</p><a href={t.faers_source_url || undefined} target="_blank" rel="noreferrer">View FAERS reports ↗</a></details>}
    <Issues issues={t.issues} />
  </article>;
}

function TreatmentList({ data }: { data: Treatments }) {
  return <><PlainLanguageKey /><Issues issues={data.issues} />{data.treatments.map(t => <TreatmentCard key={t.treatment_name} treatment={t} />)}
    {!data.treatments.length && !data.issues.length && <p className="muted">No additional treatment was identified in the guideline retrieved.</p>}</>;
}

function App() {
  const [disease, setDisease] = useState("");
  const [page, setPage] = useState<Page | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const suggestions = diseaseSuggestions.filter(name => name.toLowerCase().includes(disease.trim().toLowerCase())).slice(0, 5);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!disease.trim() || loading) return;
    setLoading(true); setError(""); setPage(null);
    try {
      const base = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
      const response = await fetch(`${base}/api/disease/${encodeURIComponent(disease.trim())}`);
      if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error("We could not reach the disease information service.");
      setPage(await response.json());
    } catch (err) { setError(err instanceof Error ? err.message : "Something went wrong."); }
    finally { setLoading(false); }
  }

  return <main>
    <header className="hero">
      <div className="hero-copy"><div className="brand"><CompassMark small /><span>CLINICAL COMPASS</span></div>
        <p className="eyebrow">A clearer path through a new diagnosis</p><h1>Understand your health,<br /><span>one step at a time.</span></h1>
        <p className="intro">Plain-language guidance for you and the people who care about you.</p>
      </div>
      <div className="hero-art" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="hero-compass"><CompassMark /></div><span className="orbit-dot dot-one" /><span className="orbit-dot dot-two" /><span className="orbit-dot dot-three" /></div>
    </header>

    <div className="notice"><span className="notice-mark" aria-hidden="true">i</span><p>For learning and conversation with your doctor. This guide is not a diagnosis or medical advice.</p></div>
    <form className="search-card" onSubmit={submit}><label htmlFor="disease">What would you like to learn about?</label><p className="search-hint">Enter a disease or health condition—we’ll help with common names and spelling.</p><div className="search"><span className="search-icon" aria-hidden="true">⌕</span><input id="disease" list="disease-suggestions" required maxLength={120} value={disease} onChange={e => setDisease(e.target.value)} placeholder="Try rheumatoid arthritis" /><datalist id="disease-suggestions">{diseaseSuggestions.map(name => <option key={name} value={name} />)}</datalist><button disabled={loading}>{loading ? "Searching…" : <>Explore condition <span aria-hidden="true">→</span></>}</button></div>{disease.trim() && suggestions.length > 0 && <div className="suggestions" aria-label="Condition suggestions">{suggestions.map(name => <button type="button" key={name} onClick={() => setDisease(name)}>{name}<span>Use this name →</span></button>)}</div>}<p className="search-example">Try an abbreviation or alternate spelling, such as “RA,” “T2D,” or “retts syndrome.”</p></form>

    {loading && <div className="loading-card" role="status"><span className="loader" /><div><strong>Finding clear, reliable information</strong><p>Checking guidelines, medicine labels, and published studies. This may take a little while.</p></div></div>}
    {error && <div className="error" role="alert">{error} Please try again.</div>}
    {page && <div className="results" aria-live="polite"><div className="results-title"><div><p className="eyebrow">YOUR CONDITION GUIDE</p><h2>{page.disease}</h2></div><span className="guide-badge"><CompassMark small /> Your guide</span></div>
      {page.partial && <div className="notice notice-partial"><span className="notice-mark">i</span><p>Some details could not be confirmed from the sources retrieved. Notes are shown where information is missing.</p></div>}
      <nav className="section-nav" aria-label="On this page">{sections.map((title, index) => <a key={title} href={`#${sectionId(title)}`}><span>{String(index + 1).padStart(2, "0")}</span>{title}</a>)}</nav>
      <section className="card glance-card" id="at-a-glance"><div className="section-heading"><span className="step-number">01</span><h2>At a glance</h2></div><div className="glance-content"><div><p className="glance-label">THE SHORT VERSION</p><h3>{glanceText(page.disease, 'error' in page.overview ? '' : page.overview.plain_language_summary)}</h3><p className="glance-note">This is a simple starting point. Everyone’s experience can be different.</p></div><ConditionIllustration disease={page.disease} /></div></section>
      <Section<Overview> title="Overview" step="02" value={page.overview}>{v => <><div className="overview-lead"><div><Preview text={v.plain_language_summary} words={40} /><Source source={v.source} /></div><ConditionIllustration disease={page.disease} /></div><div className="overview-grid"><div className="overview-list"><div className="overview-icon symptom-icon" aria-hidden="true">⌁</div><div><h3>What you may notice</h3><ul>{v.common_symptoms.map(x => <li key={x}>{x}</li>)}</ul></div></div><div className="overview-list"><div className="overview-icon cause-icon" aria-hidden="true">✳</div><div><h3>What can contribute</h3><ul>{v.causes_or_risk_factors.map(x => <li key={x}>{x}</li>)}</ul></div></div></div></>}</Section>
      <Section<Standard> title="Standard of care" step="02" value={page.standard_of_care}>{v => <><div className="standard-highlight"><span className="mini-label">GUIDELINE-RECOMMENDED CARE</span><h3>{v.treatment_name}</h3><Preview text={v.description} words={38} /></div><div className="standard-meta"><span>Guideline</span><strong>{v.guideline_name}</strong><Source source={v.guideline_source} /></div><div className="benefit-block"><div className="subheading-row"><h4>How well can treatment work?</h4><span className="mini-label">Study results</span></div><p className="muted">Results depend on the person and the outcome a study measures.</p>{v.efficacy_treatment_name && <p className="study-drug">Evidence for <strong>{v.efficacy_treatment_name}</strong></p>}<Evidence finding={v.efficacy} empty="No treatment benefit could be verified in the studies retrieved." /></div><details className="prescribing-note"><summary>About prescribing volume</summary><p>{v.prescribing_volume_status}</p><p>Options are ordered by the cited guideline, not by prescription totals.</p></details><Issues issues={v.issues} /></>}</Section>
      <Section<Treatments> title="Safety of standard treatment" step="03" value={page.label_safety}>{v => <TreatmentList data={v} />}</Section>
      <Section<Treatments> title="Other common treatments" step="04" value={page.alternative_treatments}>{v => <TreatmentList data={v} />}</Section>
      <Section<{ questions: string[] }> title="Questions for your Doctor" step="05" value={{ questions: [
        `Given my ${page.disease} and health history, which treatment options may fit me best?`,
        "What benefits should we look for, how will we measure them, and when should we check in?",
        "Which side effects should I watch for, and who should I contact if I notice them?",
      ] }}>{v => <><p className="questions-intro">You can bring these questions to your next visit and write down the answers.</p><ol className="question-list">{v.questions.map((question, index) => <li key={question}><span className="question-number">{index + 1}</span><p>{question}</p></li>)}</ol></>}</Section>
      <Section<{ trials: Trial[] }> title="Clinical trials" step="06" value={page.trials}>{v => <><div className="trial-intro"><span className="trial-icon" aria-hidden="true">✳</span><p>Studies currently seeking volunteers in the US, with at least 100 participants and Phase 2 or later. Study teams confirm openings and eligibility.</p></div>{v.trials.length ? <div className="trial-grid">{v.trials.map(t => <article className="trial" key={t.study_url}><div className="trial-top"><span className="badge">{t.phase.replace("PHASE", "Phase ")}</span><span className="enrollment"><strong>{t.enrollment}</strong> people</span></div><h3>{t.title}</h3><details className="read-more"><summary>About this study</summary><p>{t.brief_summary}</p></details><p className="trial-location"><span aria-hidden="true">⌖</span> {t.location}</p><a className="trial-link" href={t.study_url} target="_blank" rel="noreferrer">See details &amp; contact the team <span aria-hidden="true">↗</span></a></article>)}</div> : <p className="muted">No matching studies were returned in this search.</p>}</>}</Section>
      <footer className="page-footer"><CompassMark small /><p>Use this guide to help start a conversation with your care team.</p></footer>
    </div>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
