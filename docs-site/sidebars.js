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
        'user-guide/profile-sharing-permissions',
        'user-guide/advanced-configuration',
        'user-guide/creating-custom-styles',
        'user-guide/design-systems',
        'user-guide/uploading-images',
        'user-guide/exporting-to-google-slides',
        'user-guide/retrieving-feedback',
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
        'technical/slide-host-frame-contract',
        'technical/slide-editing-robustness-fixes',
        'technical/configuration-validation',
        'technical/export-features',
        'technical/lakebase-integration',
        'technical/llm-as-judge-verification',
        'technical/multi-user-concurrency',
        'technical/permissions-model',
        'technical/presentation-mode',
        'technical/profile-switch-genie-flow',
        'technical/save-points-versioning',
        'technical/url-routing',
        'technical/image-upload',
        'technical/design-system-library',
        'technical/design-system-bundle-format',
        'technical/google-slides-integration',
        'technical/feedback-system',
        'technical/mcp-server',
        'technical/mcp-integration-guide',
        'technical/tools-expansion',
        'technical/usage-analytics',
        'technical/request-monitoring',
        'technical/mlflow-uc-tracing',
      ],
    },
  ],

};

module.exports = sidebars;

