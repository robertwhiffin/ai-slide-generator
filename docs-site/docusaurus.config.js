// @ts-check
// Note: type annotations allow type checking and IDEs autocompletion

const {themes} = require('prism-react-renderer');
const path = require('path');

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Databricks tellr',
  tagline: 'Turn hours of slide work into minutes',
  favicon: 'img/favicon.ico',

  // Set the production url of your site here
  // Replace 'your-username' with your actual GitHub username or organization name
  url: 'https://tellr.github.io',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For GitHub pages deployment, it is often '/<projectName>/'
  baseUrl: '/tellr/',

  // GitHub pages deployment config.
  // Replace 'your-username' with your actual GitHub username or organization name
  organizationName: 'tellr', // Your GitHub username or org (e.g., 'databricks' or 'puneetjain')
  projectName: 'tellr', // Your repository name

  onBrokenLinks: 'throw',
  markdown: {
    format: 'mdx',
  },

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          path: path.resolve(__dirname, '../docs'),
          sidebarPath: './sidebars.js',
          // Remove this to remove the "edit this page" links.
          editUrl: undefined,
        },
        blog: false, // Disable blog
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      // Replace with your project's social card
      image: 'img/docusaurus-social-card.jpg',
      navbar: {
        title: 'Databricks tellr',
        logo: {
          alt: 'tellr Logo',
          src: 'img/logo.svg',
        },
        hideOnScroll: true,
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'gettingStarted',
            position: 'left',
            label: 'Getting Started',
          },
          {
            type: 'docSidebar',
            sidebarId: 'userGuide',
            position: 'left',
            label: 'User Guide',
          },
          {
            type: 'docSidebar',
            sidebarId: 'technical',
            position: 'left',
            label: 'Technical',
          },
          {
            type: 'docSidebar',
            sidebarId: 'api',
            position: 'left',
            label: 'API Reference',
          },
          {
            // Replace 'your-username' with your actual GitHub username or organization name
            href: 'https://github.com/your-username/tellr',
            label: 'GitHub',
            position: 'right',
            className: 'header-github-link',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Documentation',
            items: [
              {
                label: 'Getting Started',
                to: '/docs/getting-started/installation',
              },
              {
                label: 'User Guide',
                to: '/docs/user-guide/generating-slides',
              },
              {
                label: 'API Reference',
                to: '/docs/api/overview',
              },
              {
                label: 'Technical Docs',
                to: '/docs/technical/backend-overview',
              },
            ],
          },
          {
            title: 'Resources',
            items: [
              {
                label: 'Quickstart',
                to: '/docs/getting-started/quickstart',
              },
              {
                label: 'Local Development',
                to: '/docs/getting-started/local-development',
              },
              {
                label: 'Configuration',
                to: '/docs/user-guide/advanced-configuration',
              },
            ],
          },
          {
            title: 'Community',
            items: [
              {
                // Replace 'your-username' with your actual GitHub username or organization name
                label: 'GitHub',
                href: 'https://github.com/your-username/tellr',
              },
            ],
          },
        ],
        copyright: `Copyright © ${new Date().getFullYear()} Databricks tellr. Built with Docusaurus.`,
      },
      prism: {
        theme: themes.github,
        darkTheme: themes.dracula,
      },
    }),
};

module.exports = config;

