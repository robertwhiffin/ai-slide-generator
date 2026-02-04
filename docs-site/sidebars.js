/**
 * Creating a sidebar enables you to:
 - create an ordered group of docs
 - render a sidebar for each doc of that group
 - provide next/previous navigation

 The sidebars can be generated from the filesystem, or explicitly defined here.

 Create as many sidebars as you want.
 */

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  gettingStarted: [
    {
      type: 'category',
      label: 'Getting Started',
      items: [
        'getting-started/installation',
        'getting-started/quickstart',
        'getting-started/local-development',
        'getting-started/how-it-works',
      ],
    },
  ],

  userGuide: [
    {
      type: 'category',
      label: 'User Guide',
      items: [
        'user-guide/generating-slides',
        'user-guide/creating-profiles',
        'user-guide/advanced-configuration',
      ],
    },
  ],

  technical: [
    {
      type: 'category',
      label: 'Technical Documentation',
      items: [
        'technical/backend-overview',
        'technical/frontend-overview',
        'technical/databricks-app-deployment',
        'technical/database-configuration',
        'technical/real-time-streaming',
        'technical/slide-parser-and-script-management',
        'technical/slide-editing-robustness-fixes',
        'technical/configuration-validation',
        'technical/export-features',
        'technical/lakebase-integration',
        'technical/llm-as-judge-verification',
        'technical/multi-user-concurrency',
        'technical/presentation-mode',
        'technical/profile-switch-genie-flow',
      ],
    },
  ],

  api: [
    {
      type: 'category',
      label: 'API Reference',
      items: [
        'api/overview',
        'api/sessions',
        'api/chat',
        'api/slides',
        'api/export',
        'api/verification',
        'api/settings',
        'api/openapi-schema',
      ],
    },
  ],
};

module.exports = sidebars;

