import React from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';

import styles from './index.module.css';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero', styles.heroBanner)}>
      <div className="container">
        <div className={styles.heroContent}>
          <h1 className={clsx('hero__title', styles.heroTitle)}>
            {siteConfig.title}
          </h1>
          <p className={clsx('hero__subtitle', styles.heroSubtitle)}>
            {siteConfig.tagline}
          </p>
          <p className={styles.heroDescription}>
            Generate presentation-ready slides from your enterprise data through natural conversation — 
            while respecting Unity Catalog permissions.
          </p>
          <div className={styles.buttons}>
            <Link
              className="button button--primary button--lg"
              to="/docs/getting-started/installation">
              Get Started →
            </Link>
            <Link
              className="button button--outline button--secondary button--lg"
              to="/docs/user-guide/generating-slides"
              style={{marginLeft: '1rem'}}>
              User Guide
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}

function TellrFeatures() {
  const features = [
    {
      title: 'Connected to Your Data',
      icon: '🔗',
      description: 'Queries your Genie spaces for live, governed data while respecting Unity Catalog permissions.',
    },
    {
      title: 'Conversational Editing',
      icon: '💬',
      description: 'Refine slides through natural language. Ask to "add a comparison to Q3" or "make the EMEA section more prominent."',
    },
    {
      title: 'Prompt-Only Mode',
      icon: '✨',
      description: 'Works without Genie for general-purpose slide generation. Perfect for any presentation needs.',
    },
    {
      title: 'Real-Time Streaming',
      icon: '⚡',
      description: 'Watch slides generate in real-time with Server-Sent Events. See progress as your presentation comes together.',
    },
    {
      title: 'LLM Verification',
      icon: '✅',
      description: 'Automatically verify slide accuracy against source data using MLflow\'s make_judge API for quality assurance.',
    },
    {
      title: 'Export & Share',
      icon: '📊',
      description: 'Export to PowerPoint, PDF, or HTML. Share polished presentations with your team instantly.',
    },
  ];

  return (
    <section className={styles.features}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2>Why Databricks tellr?</h2>
          <p>Complete the story alongside Genie and Dashboards: conversational analytics, conversational dashboards, and now <strong>conversational presentations</strong>.</p>
        </div>
        <div className="row">
          {features.map(({title, icon, description}, idx) => (
            <div key={idx} className="col col--4 margin-bottom--lg">
              <div className={styles.featureCard}>
                <div className={styles.featureIcon}>{icon}</div>
                <h3>{title}</h3>
                <p>{description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function QuickStartSection() {
  const quickStarts = [
    {
      title: 'Getting Started',
      description: 'Install and deploy tellr to your Databricks workspace in minutes',
      link: '/docs/getting-started/installation',
      linkText: 'Installation Guide →',
    },
    {
      title: 'User Guide',
      description: 'Step-by-step instructions for generating slides and creating profiles',
      link: '/docs/user-guide/generating-slides',
      linkText: 'User Guide →',
    },
    {
      title: 'API Reference',
      description: 'Complete API documentation with request/response schemas and examples',
      link: '/docs/api/overview',
      linkText: 'API Docs →',
    },
  ];

  return (
    <section className={styles.quickStart}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2>Quick Start</h2>
          <p>Get up and running with tellr in just a few steps</p>
        </div>
        <div className="row">
          {quickStarts.map(({title, description, link, linkText}, idx) => (
            <div key={idx} className="col col--4">
              <div className={clsx('card', styles.quickStartCard)}>
                <div className="card__header">
                  <h3>{title}</h3>
                </div>
                <div className="card__body">
                  <p>{description}</p>
                </div>
                <div className="card__footer">
                  <Link className="button button--primary button--block" to={link}>
                    {linkText}
                  </Link>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function DocumentationSections() {
  const sections = [
    {
      title: 'Technical Documentation',
      description: 'Architecture, deployment, and implementation details',
      items: [
        {label: 'Backend Overview', to: '/docs/technical/backend-overview'},
        {label: 'Frontend Overview', to: '/docs/technical/frontend-overview'},
        {label: 'Databricks Deployment', to: '/docs/technical/databricks-app-deployment'},
        {label: 'Database Configuration', to: '/docs/technical/database-configuration'},
      ],
    },
    {
      title: 'API Reference',
      description: 'Complete API documentation for all endpoints',
      items: [
        {label: 'API Overview', to: '/docs/api/overview'},
        {label: 'Sessions API', to: '/docs/api/sessions'},
        {label: 'Chat API', to: '/docs/api/chat'},
        {label: 'Slides API', to: '/docs/api/slides'},
        {label: 'Export API', to: '/docs/api/export'},
        {label: 'Verification API', to: '/docs/api/verification'},
      ],
    },
  ];

  return (
    <section className={styles.documentation}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2>Documentation</h2>
          <p>Explore comprehensive guides and reference materials</p>
        </div>
        <div className="row">
          {sections.map(({title, description, items}, idx) => (
            <div key={idx} className="col col--6">
              <div className={styles.docSection}>
                <h3>{title}</h3>
                <p className={styles.docDescription}>{description}</p>
                <ul className={styles.docList}>
                  {items.map(({label, to}, itemIdx) => (
                    <li key={itemIdx}>
                      <Link to={to}>{label}</Link>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={`${siteConfig.title} Documentation`}
      description="Generate presentation-ready slides from your enterprise data through natural conversation">
      <HomepageHeader />
      <main>
        <TellrFeatures />
        <QuickStartSection />
        <DocumentationSections />
      </main>
    </Layout>
  );
}
