import "./Hero.css";

const NAV_LINKS = ["Women", "Men", "Accessories", "About"];

function SearchIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M11.667 11.667 14 14M13 7.333A5.667 5.667 0 1 1 1.667 7.333a5.667 5.667 0 0 1 11.333 0Z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="m4 6 4 4 4-4"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function Hero() {
  return (
    <section className="hero">
      <header className="hero__nav">
        <div className="hero__logo">ONY</div>

        <nav className="hero__links" aria-label="Primary">
          {NAV_LINKS.map((label) => (
            <a key={label} href="#" className="hero__link">
              {label}
            </a>
          ))}
        </nav>

        <div className="hero__actions">
          <button className="hero__icon-btn" aria-label="Search">
            <SearchIcon />
          </button>
          <button className="hero__lang-btn">
            <span>Eng</span>
            <ChevronDownIcon />
          </button>
          <button className="hero__menu-btn" aria-label="Menu">
            <span />
            <span />
            <span />
          </button>
        </div>
      </header>

      <div className="hero__content">
        <h1 className="hero__headline">
          Global design &amp; technology studio accelerating tomorrow&rsquo;s ideas
        </h1>
      </div>

      <div className="hero__cta">
        <button className="hero__discover">Discover</button>
      </div>
    </section>
  );
}
