/**
 * Mock data for API responses based on observed network traffic.
 * These mocks simulate the backend responses for testing.
 */
import type {
  AgentDefinitionWorkbenchResponse,
  AgentKey,
  AssemblyRulesV1,
  AssemblyRulesV2,
  CanonicalFieldDescriptor,
  ContentIdentity,
  DraftDefinition,
  DraftSaveConflictResponse,
  DraftSaveRequest,
  DraftSaveSuccessResponse,
  DraftValidationErrorResponse,
  FieldDescriptor,
  LegacyPromptSourceResponse,
  ModelAgentNode,
  ProtectedStageView,
  SystemModelEndpoint,
  TestCaseListEntry,
  TestRunEvidence,
} from '../../src/api/agentDefinitions';

// Profiles endpoint returns an array directly (GET /api/profiles)
export const mockProfiles = [
  {
    id: 1,
    name: "Sales Analytics",
    description: "Analytics profile for sales data insights",
    is_default: true,
    is_my_default: true,
    agent_config: {
      tools: [{ type: "genie", space_id: "01JGKX5N2PWQV8ABC123DEF456", space_name: "Sales Data Space", description: null, conversation_id: null }],
      slide_style_id: 1,
      deck_prompt_id: 1,
      system_prompt: null,
      slide_editing_instructions: null,
    },
    created_at: "2026-01-08T20:10:29.720015",
    created_by: "system",
    updated_at: "2026-01-08T20:10:29.720025",
  },
  {
    id: 2,
    name: "Marketing Reports",
    description: "Marketing campaign performance reports",
    is_default: false,
    agent_config: {
      tools: [{ type: "genie", space_id: "01JGKX5N2PWQV8XYZ789GHI012", space_name: "Marketing Analytics Space", description: null, conversation_id: null }],
      slide_style_id: 2,
      deck_prompt_id: 2,
      system_prompt: null,
      slide_editing_instructions: null,
    },
    created_at: "2026-01-08T20:10:29.724407",
    created_by: "system",
    updated_at: "2026-01-08T20:10:29.724411",
  }
];

// Deck prompts endpoint returns { prompts: [...], total: n }
export const mockDeckPrompts = {
  prompts: [
    {
      id: 1,
      name: "Monthly Review",
      description: "Template for consumption review meetings. Analyzes usage trends, identifies key drivers, and highlights areas for optimization.",
      category: "Review",
      prompt_content: "Create a consumption review presentation...",
      is_active: true,
      created_by: "system",
      created_at: "2026-01-08T20:10:28.689395",
      updated_by: "system",
      updated_at: "2026-01-08T20:10:28.689398"
    },
    {
      id: 2,
      name: "Executive Summary",
      description: "High-level overview format for executive audiences. Focuses on key metrics and strategic insights.",
      category: "Summary",
      prompt_content: "Create an executive summary presentation...",
      is_active: true,
      created_by: "system",
      created_at: "2026-01-08T20:10:28.689399",
      updated_by: "system",
      updated_at: "2026-01-08T20:10:28.689400"
    },
    {
      id: 3,
      name: "Quarterly Business Review",
      description: "Template for QBR presentations. Covers performance metrics, achievements, challenges, and strategic recommendations.",
      category: "Report",
      prompt_content: "Create a QBR presentation...",
      is_active: true,
      created_by: "system",
      created_at: "2026-01-08T20:10:28.689398",
      updated_by: "system",
      updated_at: "2026-01-08T20:10:28.689399"
    },
    {
      id: 4,
      name: "Use Case Analysis",
      description: "Template for analyzing use case progression and identifying blockers or accelerators.",
      category: "Analysis",
      prompt_content: "Create a use case analysis presentation...",
      is_active: true,
      created_by: "system",
      created_at: "2026-01-08T20:10:28.689400",
      updated_by: "system",
      updated_at: "2026-01-08T20:10:28.689401"
    }
  ],
  total: 4
};

// Slide styles endpoint returns { styles: [...], total: n }
export const mockSlideStyles = {
  styles: [
    {
      id: 1,
      name: "System Default",
      description: "Protected system style. Use this as a template when creating your own custom styles.",
      category: "System",
      style_content: "/* System default CSS */",
      is_active: true,
      is_system: true,
      is_default: true,
      created_by: "system",
      created_at: "2026-01-08T20:10:28.692105",
      updated_by: "system",
      updated_at: "2026-01-08T20:10:28.692107"
    },
    {
      id: 2,
      name: "Corporate Theme",
      description: "Professional corporate styling with clean typography and modern layout.",
      category: "Brand",
      style_content: "/* Databricks brand style CSS */",
      is_active: true,
      is_system: false,
      is_default: false,
      created_by: "system",
      created_at: "2026-01-08T20:10:28.695640",
      updated_by: "system",
      updated_at: "2026-01-08T20:10:28.695641"
    },
    {
      id: 3,
      name: "Archived Legacy",
      description: "Retired style kept for historical reference.",
      category: "Brand",
      style_content: "/* archived */",
      is_active: false,
      is_system: false,
      is_default: false,
      created_by: "system",
      created_at: "2026-01-08T20:10:28.700000",
      updated_by: "system",
      updated_at: "2026-01-08T20:10:28.700000"
    }
  ],
  total: 3
};

// Sessions endpoint returns { sessions: [...], count: n }
export const mockSessions = {
  sessions: [
    {
      session_id: "b1b4d8e3-6cf6-47cb-ad58-9fdc6ad205cc",
      user_id: null,
      created_by: "dev@local.dev",
      title: "Session 2026-01-08 20:38",
      created_at: "2026-01-08T20:38:56.749592",
      last_activity: "2026-01-08T20:42:11.058737",
      message_count: 4,
      has_slide_deck: true,
      profile_id: 1,
      profile_name: "Sales Analytics"
    },
    {
      session_id: "a2c5f1d9-8ef7-48dc-be69-0ead7be316dd",
      user_id: null,
      created_by: "dev@local.dev",
      title: "Session 2026-01-08 20:20",
      created_at: "2026-01-08T20:20:26.292382",
      last_activity: "2026-01-08T20:21:02.581630",
      message_count: 4,
      has_slide_deck: true,
      profile_id: 2,
      profile_name: "Marketing Reports"
    }
  ],
  count: 2
};

export const mockSlides = [
  {
    index: 0,
    title: "Benefits of Cloud Computing",
    html_content: `<div class="slide-container">
      <h1>Benefits of Cloud Computing</h1>
      <p class="subtitle">Transforming business operations through scalability, cost efficiency, and innovation</p>
    </div>`,
    verification_status: "unable_to_verify",
    hash: "f46b1cb8"
  },
  {
    index: 1,
    title: "Cost Savings Drive Cloud Adoption",
    html_content: `<div class="slide-container">
      <h1>Cost Savings Drive Cloud Adoption</h1>
      <p>Organizations reduce IT infrastructure costs by 35% on average within the first year</p>
      <div class="stats">
        <div class="stat"><span class="value">35%</span><span class="label">Average Cost Reduction</span></div>
        <div class="stat"><span class="value">62%</span><span class="label">Lower Maintenance Costs</span></div>
        <div class="stat"><span class="value">48%</span><span class="label">Reduced Energy Expenses</span></div>
      </div>
    </div>`,
    verification_status: "verified",
    hash: "2b11b64e"
  },
  {
    index: 2,
    title: "Key Benefits Beyond Cost",
    html_content: `<div class="slide-container">
      <h1>Key Benefits Beyond Cost</h1>
      <p>Cloud computing delivers strategic advantages across operations and innovation</p>
      <div class="benefits">
        <div class="benefit"><span class="number">1</span> Scalability & Flexibility</div>
        <div class="benefit"><span class="number">2</span> Enhanced Security</div>
        <div class="benefit"><span class="number">3</span> Remote Collaboration</div>
        <div class="benefit"><span class="number">4</span> Automatic Updates</div>
      </div>
    </div>`,
    verification_status: "unable_to_verify",
    hash: "159c0167"
  }
];

export const mockVerificationResponse = {
  status: "verified",
  message: "Slide verified successfully",
  details: null
};

// ============================================
// Agent Config & New Profile API Mocks
// ============================================

// Default agent config returned by GET /api/sessions/:id/agent-config
export const mockDefaultAgentConfig = {
  tools: [],
  slide_style_id: 1,
  deck_prompt_id: null,
  system_prompt: null,
  slide_editing_instructions: null,
};

// Alias for backward compatibility — mockProfiles now has the unified shape
export const mockProfileSummaries = mockProfiles;

// Available tools returned by GET /api/tools/available
export const mockAvailableTools = [
  {
    type: "genie",
    space_id: "01JGKX5N2PWQV8ABC123DEF456",
    space_name: "Sales Data Space",
    description: "Contains sales and revenue data",
  },
  {
    type: "genie",
    space_id: "01JGKX5N2PWQV8XYZ789GHI012",
    space_name: "Marketing Analytics Space",
    description: "Marketing campaign metrics",
  },
];

// ============================================
// Legacy Profile Operation Mocks (still used by /profiles page)
// ============================================

// Profile load/switch response
export const mockProfileLoadResponse = {
  status: "reloaded",
  profile_id: 1
};

// Profile creation response
export const mockProfileCreateResponse = {
  id: 3,
  name: "New Test Profile",
  description: "A test profile created via wizard",
  is_default: false,
  created_at: "2026-01-30T10:00:00.000000",
  created_by: "test",
  updated_at: "2026-01-30T10:00:00.000000",
  updated_by: null
};

// Profile update response
export const mockProfileUpdateResponse = {
  id: 1,
  name: "Updated Profile Name",
  description: "Updated description",
  is_default: true,
  created_at: "2026-01-08T20:10:29.720015",
  created_by: "system",
  updated_at: "2026-01-30T10:00:00.000000",
  updated_by: "test"
};

// Duplicate name error response (409 Conflict)
export const mockDuplicateNameError = {
  detail: "Failed to create profile"
};

// Delete last profile error response (400 Bad Request)
export const mockDeleteLastProfileError = {
  detail: "Cannot delete the last profile"
};

// Mock Genie spaces for wizard step 2
export const mockGenieSpaces = {
  spaces: [
    {
      space_id: "01JGKX5N2PWQV8ABC123DEF456",
      space_name: "Sales Data Space",
      description: "Contains sales and revenue data"
    },
    {
      space_id: "01JGKX5N2PWQV8XYZ789GHI012",
      space_name: "Marketing Analytics Space",
      description: "Marketing campaign metrics"
    }
  ],
  total: 2
};

// Mock single Genie space lookup response
export const mockGenieSpaceLookup = {
  space_id: "01JGKX5N2PWQV8ABC123DEF456",
  space_name: "Sales Data Space",
  description: "Contains sales and revenue data"
};

// Mock profile with full details (for ProfileDetailView)
export const mockProfileDetail = {
  id: 1,
  name: "Sales Analytics",
  description: "Analytics profile for sales data insights",
  is_default: true,
  created_at: "2026-01-08T20:10:29.720015",
  created_by: "system",
  updated_at: "2026-01-08T20:10:29.720025",
  updated_by: null,
  genie_spaces: [
    {
      space_id: "01JGKX5N2PWQV8ABC123DEF456",
      space_name: "Sales Data Space",
      description: "Contains sales and revenue data"
    }
  ],
  slide_style: {
    id: 1,
    name: "System Default",
    category: "System"
  },
  deck_prompt: {
    id: 1,
    name: "Monthly Review",
    category: "Review"
  }
};

// ============================================
// Slide Style Operation Mocks
// ============================================

// Slide style creation response
export const mockStyleCreateResponse = {
  id: 99,
  name: "New Test Style",
  description: "Test style created via E2E",
  category: "Custom",
  style_content: "/* test CSS */",
  is_active: true,
  is_system: false,
  created_by: "test",
  created_at: "2026-01-31T10:00:00.000000",
  updated_by: null,
  updated_at: "2026-01-31T10:00:00.000000"
};

// Slide style update response
export const mockStyleUpdateResponse = {
  id: 2,
  name: "Updated Style Name",
  description: "Updated description",
  category: "Custom",
  style_content: "/* updated CSS */",
  is_active: true,
  is_system: false,
  created_by: "system",
  created_at: "2026-01-08T20:10:28.695640",
  updated_by: "test",
  updated_at: "2026-01-31T10:00:00.000000"
};

// Duplicate style name error response (409 Conflict)
export const mockStyleDuplicateError = {
  detail: "Style with this name already exists"
};

// Cannot delete system style error response (400 Bad Request)
export const mockDeleteSystemStyleError = {
  detail: "Cannot delete system style"
};

// ============================================
// Design System Library Mocks (Phase 4)
// ============================================
//
// Everything here is SYNTHETIC — a fake "Acme" brand, dummy hex, and placeholder
// assets — mirroring the backend's tests/unit/conftest_design_system.py fixture,
// per the public-repo hygiene rule (no real brand content ever ships).

// GET /api/settings/design-systems -> { design_systems: [...], total: n }
export const mockDesignSystems = {
  design_systems: [
    {
      id: 1,
      name: "Acme Design System",
      description: "Synthetic fixture brand — not a real design system.",
      created_by: "system",
      published: true,
      is_default: true,
      is_active: true,
      version: 1,
      token_count: 3,
      asset_count: 3,
      template_count: 2,
      created_at: "2026-02-01T10:00:00.000000",
      updated_at: "2026-02-01T10:00:00.000000",
    },
    {
      id: 2,
      name: "Nimbus Theme",
      description: "A second synthetic design system for list rendering.",
      created_by: "system",
      published: false,
      is_default: false,
      is_active: true,
      version: 2,
      token_count: 1,
      asset_count: 1,
      template_count: 0,
      created_at: "2026-02-02T10:00:00.000000",
      updated_at: "2026-02-02T10:00:00.000000",
    },
  ],
  total: 2,
};

// GET /api/settings/design-systems/{id} -> DesignSystemDetail
export const mockDesignSystemDetail = {
  id: 1,
  name: "Acme Design System",
  description: "Synthetic fixture brand — not a real design system.",
  created_by: "system",
  published: true,
  is_default: true,
  is_active: true,
  version: 1,
  token_count: 3,
  asset_count: 3,
  template_count: 2,
  created_at: "2026-02-01T10:00:00.000000",
  updated_at: "2026-02-01T10:00:00.000000",
  manifest_json: {
    name: "Acme Design System",
    description: "Synthetic fixture brand — not a real design system.",
    version: "1.0.0",
    templates: [
      { name: "Title Slide", description: "Centered hero with logo lockup." },
      { name: "Two Column", description: "Left text, right chart." },
    ],
    cards: [{ name: "Stat Card", description: "Big number + label." }],
  },
  compiled_style_content: ":root {\n  --brand-core-primary: #123456;\n}",
  tokens: [
    { id: 1, group: "core", name: "primary", value: "#123456" },
    { id: 2, group: "accents", name: "lava", value: "#EB4A34" },
    { id: 3, group: "spacing", name: "md", value: "16px" },
  ],
  assets: [
    {
      id: 10,
      kind: "logo",
      filename: "logo.svg",
      mime: "image/svg+xml",
      size_bytes: 120,
      width: 120,
      height: 40,
      url: "/api/settings/design-systems/1/assets/10",
      thumbnail_url: null,
    },
    {
      id: 11,
      kind: "background",
      filename: "hero-bg.png",
      mime: "image/png",
      size_bytes: 512,
      width: 16,
      height: 16,
      url: "/api/settings/design-systems/1/assets/11",
      thumbnail_url: "/api/settings/design-systems/1/assets/11/thumbnail",
    },
    {
      id: 12,
      kind: "font",
      filename: "acme-sans.woff2",
      mime: "font/woff2",
      size_bytes: 2048,
      width: null,
      height: null,
      url: "/api/settings/design-systems/1/assets/12",
      thumbnail_url: null,
    },
  ],
};

// POST /api/settings/design-systems/import (success) -> DesignSystemDetail (201)
export const mockDesignSystemImportResponse = {
  ...mockDesignSystemDetail,
  id: 99,
  name: "Imported Design System",
  description: "Freshly imported synthetic bundle.",
  published: false,
  is_default: false,
};

// POST /api/settings/design-systems/import (validation failure) -> 400
export const mockDesignSystemImportError = {
  detail: "Bundle is missing its manifest (_ds_manifest.json).",
};

// POST /api/settings/design-systems/{id}/set-default -> DesignSystemDetail
export const mockDesignSystemSetDefaultResponse = {
  ...mockDesignSystemDetail,
  id: 2,
  name: "Nimbus Theme",
  is_default: true,
};

// GET /api/settings/design-systems/{id}/templates -> addressable templates (Phase 4)
export const mockDesignSystemTemplates = {
  templates: [
    {
      id: 1,
      name: "Acme Cover",
      description: "Centered hero with logo lockup.",
      entry_path: "templates/cover/index.html",
      thumbnail_url: "/api/settings/design-systems/1/templates/1/thumbnail",
    },
  ],
  total: 1,
};

// Template set with a screenshot-less entry (real Claude Design exports ship
// no preview images): id 2 exercises the live-render mini-card fallback.
export const mockDesignSystemTemplatesWithLive = {
  templates: [
    {
      id: 1,
      name: "Acme Cover",
      description: "Centered hero with logo lockup.",
      entry_path: "templates/cover/index.html",
      thumbnail_url: "/api/settings/design-systems/1/templates/1/thumbnail",
    },
    {
      id: 2,
      name: "Acme Content",
      description: "Body layout without a shipped screenshot.",
      entry_path: "templates/content/index.html",
      thumbnail_url: null,
    },
  ],
  total: 2,
};

// GET /api/settings/design-systems/{id}/templates/2/source -> stored sources
// for the sandboxed live preview (JSON; synthetic Acme only).
export const mockDesignSystemTemplateSource = {
  id: 2,
  name: "Acme Content",
  layout_html:
    '<!doctype html><html><head><style>.slide{width:1280px;height:720px;background:var(--brand-core-primary);color:#ffffff;}</style></head>' +
    '<body><section class="slide"><h1>Acme Content Layout</h1></section></body></html>',
  token_css: ":root { --brand-core-primary: #123456; }",
};

// A MULTI-SLIDE template source: the expanded viewer paginates one slide
// section at a time, so it needs a layout with several `.slide` roots.
// Each section is identifiable by its own heading text. Synthetic Acme only.
export const mockDesignSystemTemplateSourceMultiSlide = {
  id: 2,
  name: "Acme Content",
  layout_html:
    '<!doctype html><html><head><style>.slide{width:1280px;height:720px;background:var(--brand-core-primary);color:#ffffff;}</style></head>' +
    '<body>' +
    '<section class="slide"><h1>Acme Slide One</h1></section>' +
    '<section class="slide"><h1>Acme Slide Two</h1></section>' +
    '<section class="slide"><h1>Acme Slide Three</h1></section>' +
    '</body></html>',
  token_css: ":root { --brand-core-primary: #123456; }",
};

// A template whose slide sections are wrapped in a CUSTOM ELEMENT harness, the
// shape real Claude Design exports ship: `<deck-stage>` plus the author's own
// pre-upgrade guard `deck-stage:not(:defined){visibility:hidden}`.
//
// A preview frame runs NO scripts (sandbox="" and a CSP with no script-src), so
// that element can never be registered: it stays permanently :not(:defined),
// the guard hides every slide for good, and all that is left to see is the body
// background. Slides are `position:absolute; inset:0` exactly as the real
// templates are, so this also pins the "cards must show the FIRST slide, not
// the last one stacked on top" behavior. Synthetic Acme only.
export const mockDesignSystemTemplateSourceCustomElementHarness = {
  id: 2,
  name: "Acme Content",
  layout_html:
    "<!doctype html><html><head><style>" +
    "html,body{margin:0;background:#123456;}" +
    "deck-stage:not(:defined){visibility:hidden}" +
    ".slide{position:absolute;inset:0;display:flex;flex-direction:column;}" +
    "</style></head>" +
    '<body><deck-stage width="1280" height="720">' +
    '<section data-label="One"><div class="slide"><h1>Acme Harness Slide One</h1></div></section>' +
    '<section data-label="Two"><div class="slide"><h1>Acme Harness Slide Two</h1></div></section>' +
    "</deck-stage></body></html>",
  token_css: ":root { --brand-core-primary: #123456; }",
};

// GET /api/settings/design-systems/{id}/files -> retained source-file tree (Phase 6)
export const mockDesignSystemFiles = {
  files: [
    { path: "README.md", kind: "readme", mime: "text/markdown", size_bytes: 62 },
    { path: "SKILL.md", kind: "skill", mime: "text/markdown", size_bytes: 48 },
    { path: "assets/backgrounds/hero-bg.png", kind: "asset", mime: "image/png", size_bytes: 512 },
    { path: "assets/logo.svg", kind: "asset", mime: "image/svg+xml", size_bytes: 120 },
    { path: "colors_and_type.css", kind: "css", mime: "text/css", size_bytes: 96 },
    { path: "fonts/acme-sans.woff2", kind: "font", mime: "font/woff2", size_bytes: 2048 },
    { path: "templates/cover/index.html", kind: "template", mime: "text/html", size_bytes: 84 },
    { path: "templates/cover/preview.png", kind: "asset", mime: "image/png", size_bytes: 256 },
  ],
  total: 8,
};

// GET /api/settings/design-systems/{id}/files/{path} -> text/plain source bodies.
// Keys are the un-encoded stored paths; all content is SYNTHETIC (fake Acme).
export const mockDesignSystemFileContents: Record<string, string> = {
  "README.md": "# Acme Design System\n\nSynthetic readme for tests. Not a real brand.",
  "SKILL.md": "---\nname: acme-design\n---\n\nSynthetic SKILL doc for tests.",
  "colors_and_type.css": ":root {\n  --brand-core-primary: #123456;\n}",
  "templates/cover/index.html":
    "<!doctype html><html><body><section>Acme synthetic layout</section></body></html>",
};

// A 1x1 transparent PNG for thumbnail responses (synthetic placeholder art).
export const TINY_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

// ============================================
// Deck Prompt Operation Mocks
// ============================================

// Deck prompt creation response
export const mockPromptCreateResponse = {
  id: 99,
  name: "New Test Prompt",
  description: "Test prompt created via E2E",
  category: "Test",
  prompt_content: "This is test prompt content for E2E testing.",
  is_active: true,
  created_by: "test",
  created_at: "2026-01-31T10:00:00.000000",
  updated_by: null,
  updated_at: "2026-01-31T10:00:00.000000"
};

// Deck prompt update response
export const mockPromptUpdateResponse = {
  id: 1,
  name: "Updated Prompt Name",
  description: "Updated description",
  category: "Review",
  prompt_content: "Updated prompt content...",
  is_active: true,
  created_by: "system",
  created_at: "2026-01-08T20:10:28.689395",
  updated_by: "test",
  updated_at: "2026-01-31T10:00:00.000000"
};

// Duplicate prompt name error response (409 Conflict)
export const mockPromptDuplicateError = {
  detail: "Prompt with this name already exists"
};

// ============================================
// Image Library Mocks
// ============================================

export const mockImages = [
  {
    id: 1,
    filename: "a1b2c3d4.png",
    original_filename: "company-logo.png",
    mime_type: "image/png",
    size_bytes: 45200,
    thumbnail_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCA",
    tags: ["logo", "branding"],
    description: "Company logo for slide headers",
    category: "branding",
    uploaded_by: "dev@local.dev",
    is_active: true
  },
  {
    id: 2,
    filename: "e5f6g7h8.jpeg",
    original_filename: "product-screenshot.jpeg",
    mime_type: "image/jpeg",
    size_bytes: 312000,
    thumbnail_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCA",
    tags: ["product", "screenshot"],
    description: "Product dashboard screenshot for demo slides",
    category: "content",
    uploaded_by: "dev@local.dev",
    is_active: true
  },
  {
    id: 3,
    filename: "i9j0k1l2.png",
    original_filename: "gradient-bg.png",
    mime_type: "image/png",
    size_bytes: 128000,
    thumbnail_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCA",
    tags: ["background", "gradient"],
    description: "Dark gradient background for title slides",
    category: "background",
    uploaded_by: "dev@local.dev",
    is_active: true
  }
];

export const mockImageListResponse = {
  images: mockImages,
  total: mockImages.length
};

export const mockImageUploadResponse = {
  id: 4,
  filename: "m3n4o5p6.png",
  original_filename: "uploaded-image.png",
  mime_type: "image/png",
  size_bytes: 98000,
  thumbnail_base64: "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCA",
  tags: [],
  description: "",
  category: "content",
  uploaded_by: "dev@local.dev",
  is_active: true
};

// ============================================
// Feedback Dashboard Mocks
// ============================================

export const mockFeedbackStats = {
  weeks: [
    {
      week_start: "2026-02-10",
      week_end: "2026-02-16",
      responses: 8,
      avg_star_rating: 4.5,
      avg_nps_score: 8.3,
      total_time_saved_minutes: 480,
      time_saved_display: "8h 0m"
    },
    {
      week_start: "2026-02-03",
      week_end: "2026-02-09",
      responses: 12,
      avg_star_rating: 4.2,
      avg_nps_score: 7.9,
      total_time_saved_minutes: 720,
      time_saved_display: "12h 0m"
    },
    {
      week_start: "2026-01-27",
      week_end: "2026-02-02",
      responses: 6,
      avg_star_rating: 4.0,
      avg_nps_score: 7.5,
      total_time_saved_minutes: 360,
      time_saved_display: "6h 0m"
    },
    {
      week_start: "2026-01-20",
      week_end: "2026-01-26",
      responses: 10,
      avg_star_rating: 4.4,
      avg_nps_score: 8.1,
      total_time_saved_minutes: 540,
      time_saved_display: "9h 0m"
    }
  ],
  totals: {
    total_responses: 36,
    avg_star_rating: 4.3,
    avg_nps_score: 8.0,
    total_time_saved_minutes: 2100,
    time_saved_display: "35h 0m"
  },
  usage: {
    total_sessions: 85,
    distinct_users: 14
  }
};

export const mockFeedbackSummary = {
  period: "Last 4 weeks",
  feedback_count: 9,
  summary: "Over the past 4 weeks, users submitted 9 feedback items. The most common theme was Feature Requests (4), primarily asking for additional chart types and template customisation. Two Bug Reports mentioned text overflow on metric cards. Overall sentiment is positive with users appreciating the speed of generation and data accuracy.",
  top_themes: [
    "Additional chart types requested",
    "Template customisation options",
    "Text overflow on metric cards",
    "Positive feedback on generation speed"
  ],
  category_breakdown: {
    "Feature Request": 4,
    "Bug Report": 2,
    "Content Quality": 2,
    "UX Issue": 1
  }
};

// ============================================
// Google Slides Integration Mocks
// ============================================

export const mockGoogleCredentialsStatusConfigured = {
  has_credentials: true
};

export const mockGoogleCredentialsStatusEmpty = {
  has_credentials: false
};

export const mockGoogleAuthStatusAuthorized = {
  authorized: true
};

export const mockGoogleAuthStatusUnauthorized = {
  authorized: false
};

export const mockGoogleSlidesExportResponse = {
  presentation_id: "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
  presentation_url: "https://docs.google.com/presentation/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit"
};

/**
 * Create a streaming response for slide generation.
 * Simulates SSE (Server-Sent Events) format.
 */
export function createStreamingResponse(slides: typeof mockSlides): string {
  const events: string[] = [];

  // Start event
  events.push('data: {"type": "start", "message": "Starting slide generation..."}\n\n');

  // Progress events
  events.push('data: {"type": "progress", "message": "Generating slide 1..."}\n\n');

  // Slide events
  for (const slide of slides) {
    events.push(`data: {"type": "slide", "slide": ${JSON.stringify(slide)}}\n\n`);
  }

  // Complete event
  events.push('data: {"type": "complete", "message": "Generation complete"}\n\n');

  return events.join('');
}

// ============================================
// Agent Definition Workbench Mocks
// ============================================

const mockAssemblyRules = {
  format_version: 1,
  separator: "\n\n",
  blocks: [
    { kind: "authored_prompt", condition: "always" },
    { kind: "protected", name: "slide_frame_constraints", condition: "design_system_inactive" },
    { kind: "protected", name: "design_system_precedence", condition: "design_system_active" },
    { kind: "payload_json", condition: "always", indent: 2, default: "str" },
    {
      kind: "structured_output_binding",
      condition: "always",
      binding: "langchain.with_structured_output",
      terminal: true,
    },
  ],
} satisfies AssemblyRulesV1;

export const V1_PROTECTED_IDENTITY = { version: 1, digest: "b".repeat(64) } satisfies ContentIdentity;
export const V2_PROTECTED_IDENTITY = { version: 2, digest: "e".repeat(64) } satisfies ContentIdentity;

/** v2 schema contract identity used in schema-contract-upgrade fixtures. */
export const V2_SCHEMA_CONTRACT_IDENTITY = { version: 2, digest: "d".repeat(64) } satisfies ContentIdentity;

/**
 * The seven roles' `diagnostic_notes` descriptors, in the seven-role order, exactly as
 * the server's registry emits them. Written as strict JSON (double quotes, no trailing
 * commas, no comments) because
 * `test_client_diagnostic_notes_fixture_is_the_server_descriptor_for_all_seven_roles`
 * (`tests/unit/test_agent_definition_workbench_routes.py`) reads this block as text and
 * joins it to the live route output.
 */
export const DIAGNOSTIC_NOTES_DESCRIPTORS: Record<AgentKey, FieldDescriptor> = {
  "architect": {"name": "diagnostic_notes", "description": "Concise assumptions or ambiguities that influenced the selected intent; never substitute for `message`, `deck_spec`, `data_request`, targets, or a design proposal.", "examples": ["Assumed the request refers to the existing Q2 deck; no target slide numbers were supplied."], "schema": {"type": ["array", "null"], "default": null, "max_items": 8, "items": {"type": "string", "strip_whitespace": true, "min_length": 1, "max_length": 280}}},
  "data_analyst": {"name": "diagnostic_notes", "description": "Concise retrieval limitations, source disagreement, or interpretation assumptions; never replace `outcome`, `synthesis`, `sources`, `gap`, `reason`, or `tried_tools`.", "examples": ["The two sources use different fiscal calendars; synthesis compares calendar-quarter totals."], "schema": {"type": ["array", "null"], "default": null, "max_items": 8, "items": {"type": "string", "strip_whitespace": true, "min_length": 1, "max_length": 280}}},
  "builder": {"name": "diagnostic_notes", "description": "Concise non-executable rendering/design trade-offs or unavailable inputs; never contain HTML, scripts, image IDs, or a substitute for canonical slide output.", "examples": ["No supplied image IDs; used a text-and-chart composition."], "schema": {"type": ["array", "null"], "default": null, "max_items": 8, "items": {"type": "string", "strip_whitespace": true, "min_length": 1, "max_length": 280}}},
  "build_reviewer": {"name": "diagnostic_notes", "description": "Concise review-scope/evidence notes; never hide, replace, or add a finding outside canonical `findings`.", "examples": ["Contrast was assessed against the resolved style tokens supplied in this invocation."], "schema": {"type": ["array", "null"], "default": null, "max_items": 8, "items": {"type": "string", "strip_whitespace": true, "min_length": 1, "max_length": 280}}},
  "fixer": {"name": "diagnostic_notes", "description": "Concise reason for a narrowly limited or declined attempted fix; never replace `changed` or `change_summary`.", "examples": ["Did not alter the chart because the reported issue concerns only title overflow."], "schema": {"type": ["array", "null"], "default": null, "max_items": 8, "items": {"type": "string", "strip_whitespace": true, "min_length": 1, "max_length": 280}}},
  "fix_reviewer": {"name": "diagnostic_notes", "description": "Concise evidence about whether the original issue was resolved or a review limitation; never replace the canonical verdict/findings.", "examples": ["Verified the original overflow against the corrected title container."], "schema": {"type": ["array", "null"], "default": null, "max_items": 8, "items": {"type": "string", "strip_whitespace": true, "min_length": 1, "max_length": 280}}},
  "deck_reviewer": {"name": "diagnostic_notes", "description": "Concise deck-level review scope/limitations; never replace deck findings or introduce slide-level findings.", "examples": ["Narrative assessment used the supplied slide sequence; no presenter notes were available."], "schema": {"type": ["array", "null"], "default": null, "max_items": 8, "items": {"type": "string", "strip_whitespace": true, "min_length": 1, "max_length": 280}}}
};

/** The architect's descriptor, kept as a named sample for single-role tests. */
export const DIAGNOSTIC_NOTES_DESCRIPTOR: FieldDescriptor = DIAGNOSTIC_NOTES_DESCRIPTORS.architect;

/**
 * Each role's code-owned canonical output fields, in the seven-role order and in model
 * field order, exactly as the server derives them for display. Strict JSON for the same
 * reason as above: `test_client_canonical_field_fixture_is_the_server_display_data`
 * reads this block as text and joins it to the live route output.
 */
export const CANONICAL_FIELD_DESCRIPTORS: Record<AgentKey, CanonicalFieldDescriptor[]> = {
  "architect": [
    {"name": "intent", "type": "string", "required": true, "enum": ["discuss", "ask_data", "build", "edit", "confirm_design_contract"]},
    {"name": "message", "type": "string", "required": true, "enum": null},
    {"name": "deck_spec", "type": "DeckSpec | null", "required": false, "enum": null, "default": null},
    {"name": "data_request", "type": "DataRequest | null", "required": false, "enum": null, "default": null},
    {"name": "target_positions", "type": "array<integer>", "required": false, "enum": null, "default": []},
    {"name": "proposed_design_contract", "type": "DesignContractRef | null", "required": false, "enum": null, "default": null}
  ],
  "data_analyst": [
    {"name": "outcome", "type": "string", "required": true, "enum": ["success", "missing_data", "no_tool"]},
    {"name": "synthesis", "type": "string | null", "required": false, "enum": null, "default": null},
    {"name": "sources", "type": "array<string> | null", "required": false, "enum": null, "default": null},
    {"name": "gap", "type": "string | null", "required": false, "enum": null, "default": null},
    {"name": "tried_tools", "type": "array<string>", "required": false, "enum": null, "default": []},
    {"name": "reason", "type": "string | null", "required": false, "enum": null, "default": null}
  ],
  "builder": [
    {"name": "position", "type": "integer", "required": true, "enum": null},
    {"name": "html", "type": "string", "required": true, "enum": null},
    {"name": "scripts", "type": "string", "required": false, "enum": null, "default": ""}
  ],
  "build_reviewer": [
    {"name": "slide_index", "type": "integer", "required": true, "enum": null},
    {"name": "verdict", "type": "string", "required": true, "enum": ["clean", "fixed", "surfaced"]},
    {"name": "findings", "type": "array<Finding>", "required": false, "enum": null, "default": []}
  ],
  "fixer": [
    {"name": "position", "type": "integer", "required": true, "enum": null},
    {"name": "html", "type": "string", "required": true, "enum": null},
    {"name": "scripts", "type": "string", "required": false, "enum": null, "default": ""},
    {"name": "changed", "type": "boolean", "required": true, "enum": null},
    {"name": "change_summary", "type": "string", "required": false, "enum": null, "default": ""}
  ],
  "fix_reviewer": [
    {"name": "slide_index", "type": "integer", "required": true, "enum": null},
    {"name": "verdict", "type": "string", "required": true, "enum": ["clean", "fixed", "surfaced"]},
    {"name": "findings", "type": "array<Finding>", "required": false, "enum": null, "default": []}
  ],
  "deck_reviewer": [
    {"name": "findings", "type": "array<Finding>", "required": false, "enum": null, "default": []}
  ]
};

/**
 * The exact ordered 422 the schema-contract-upgrade route returns for an already-current
 * contract. The field is the server's unprefixed `schema_contract` (correction 18), and
 * `test_client_schema_already_current_fixture_is_the_server_issue`
 * (`tests/unit/test_prompt_assembler.py`) joins this triple to the server literal.
 */
export const SCHEMA_ALREADY_CURRENT_REJECTION: DraftValidationErrorResponse = {
  code: 'invalid_draft',
  errors: [
    {
      field: 'schema_contract',
      code: 'already_current',
      message: 'Schema contract is already current.',
    },
  ],
};

export const EMPTY_V2_ASSEMBLY_RULES = {
  format_version: 2,
  custom_blocks: [],
} satisfies AssemblyRulesV2;

/**
 * The exact protected-stage rows the Task 4 route derives for each bundle. Stage
 * identities, labels, conditions, and legal anchors mirror the server contract;
 * every `display_text` is a synthetic fixture value, which is what proves the
 * client renders server bytes instead of reconstructing protected text.
 */
function v1ProtectedStageView(agentKey: AgentKey): ProtectedStageView[] {
  const locked = { locked: true, bundle_version: 1, bundle_digest: V1_PROTECTED_IDENTITY.digest } as const;
  const rows: ProtectedStageView[] = [];
  if (agentKey === "build_reviewer") {
    rows.push({
      stage_id: "build_reviewer_deck_brief",
      label: "Deck-brief re-review",
      condition: "payload_has_deck_brief",
      display_text: "Synthetic v1 deck-brief re-review text.",
      legal_adjacent_custom_anchors: [],
      ...locked,
    });
  }
  rows.push(
    {
      stage_id: "slide_frame_constraints",
      label: "Slide frame constraints",
      condition: "design_system_inactive",
      display_text: "Synthetic v1 slide frame constraints text.",
      legal_adjacent_custom_anchors: [],
      ...locked,
    },
    {
      stage_id: "design_system_precedence",
      label: "Design system precedence",
      condition: "design_system_active",
      display_text: "Synthetic v1 design system precedence text.",
      legal_adjacent_custom_anchors: [],
      ...locked,
    },
    {
      stage_id: "runtime_payload",
      label: "Graph Version 1 runtime payload",
      condition: "always",
      display_text: "json.dumps(payload, indent=2, default=str)",
      legal_adjacent_custom_anchors: [],
      ...locked,
    },
    {
      stage_id: "structured_output_binding",
      label: "Structured-output binding",
      condition: "always",
      display_text: "langchain.with_structured_output",
      legal_adjacent_custom_anchors: [],
      ...locked,
    },
  );
  return rows;
}

export function v2ProtectedStageView(agentKey: AgentKey): ProtectedStageView[] {
  const locked = { locked: true, bundle_version: 2, bundle_digest: V2_PROTECTED_IDENTITY.digest } as const;
  const rows: ProtectedStageView[] = [];
  if (agentKey === "build_reviewer") {
    rows.push(
      {
        stage_id: "build_reviewer_criteria",
        label: "Build Reviewer criteria",
        condition: "always",
        display_text: "Synthetic v2 Build Reviewer criteria text.",
        legal_adjacent_custom_anchors: [],
        ...locked,
      },
      {
        stage_id: "build_reviewer_deck_brief",
        label: "Deck-brief re-review",
        condition: "payload_has_deck_brief",
        display_text: "Synthetic v2 deck-brief re-review text.",
        legal_adjacent_custom_anchors: ["after_deck_brief"],
        ...locked,
      },
    );
  }
  rows.push(
    {
      stage_id: "slide_frame_constraints",
      label: "Slide frame constraints",
      condition: "design_system_inactive",
      display_text: "Synthetic v2 slide frame constraints text.",
      legal_adjacent_custom_anchors: ["after_environment_constraints"],
      ...locked,
    },
    {
      stage_id: "design_system_precedence",
      label: "Design system precedence",
      condition: "design_system_active",
      display_text: "Synthetic v2 design system precedence text.",
      legal_adjacent_custom_anchors: ["after_environment_constraints"],
      ...locked,
    },
    {
      stage_id: "untrusted_data_notice",
      label: "Role-specific untrusted-data notice",
      condition: "always",
      display_text: `Synthetic v2 untrusted-data notice for ${agentKey}.`,
      legal_adjacent_custom_anchors: [],
      ...locked,
    },
    {
      stage_id: "untrusted_data_open",
      label: "Untrusted-data opening delimiter",
      condition: "always",
      display_text: "<<<UNTRUSTED_DATA>>>",
      legal_adjacent_custom_anchors: [],
      ...locked,
    },
    {
      stage_id: "runtime_payload",
      label: "Canonical runtime payload",
      condition: "always",
      display_text: "json.dumps(payload, indent=2, default=str, sort_keys=True)",
      legal_adjacent_custom_anchors: [],
      ...locked,
    },
    {
      stage_id: "untrusted_data_close",
      label: "Untrusted-data closing delimiter",
      condition: "always",
      display_text: "<<<END_UNTRUSTED_DATA>>>",
      legal_adjacent_custom_anchors: [],
      ...locked,
    },
    {
      stage_id: "structured_output_binding",
      label: "Structured-output binding",
      condition: "always",
      display_text: "langchain.with_structured_output",
      legal_adjacent_custom_anchors: [],
      ...locked,
    },
  );
  return rows;
}

const workbenchAgentNames = [
  ["architect", "Architect"],
  ["data_analyst", "Data Analyst"],
  ["builder", "Builder"],
  ["build_reviewer", "Build Reviewer"],
  ["fixer", "Fixer"],
  ["fix_reviewer", "Fix Reviewer"],
  ["deck_reviewer", "Deck Reviewer"],
] as const;

const mockModelNodes = workbenchAgentNames.map(([agentKey, displayName], index) => {
  const definition = {
    definition_version: 2,
    prompt_text: `Synthetic ${displayName} prompt — exact fixture value.`,
    model: {
      endpoint_name: "databricks-claude-opus-4-6",
      temperature: 0.7,
      max_tokens: 60000,
      top_p: 0.95,
    },
    schema_overlay: {
      field_overrides: agentKey === "architect" ? { title: { description: "Synthetic title override" } } : {},
      additional_optional_fields: agentKey === "architect" ? ["speaker_notes"] : [],
    },
    assembly_rules: mockAssemblyRules,
    protected_assembly: structuredClone(V1_PROTECTED_IDENTITY),
    schema_contract: { version: 1, digest: "c".repeat(64) },
    protected_stage_view: v1ProtectedStageView(agentKey),
    selectable_optional_fields: [],
    canonical_fields: structuredClone(CANONICAL_FIELD_DESCRIPTORS[agentKey]),
  };

  return {
    agent_key: agentKey,
    display_name: displayName,
    execution_kind: "model",
    editable: true,
    changed: false,
    published: {
      revision_id: index + 11,
      content_hash: "a".repeat(64),
      ...definition,
    },
    draft: {
      base_revision_id: index + 11,
      candidate_hash: "a".repeat(64),
      ...definition,
    },
    read_only_reason: null,
  } satisfies ModelAgentNode;
});

export const syntheticDraftDefinitions = Object.fromEntries(
  mockModelNodes.map((node) => [node.agent_key, structuredClone(node.draft)]),
) as unknown as Record<AgentKey, DraftDefinition>;

export const syntheticDraftSaveRequest = {
  lock_version: 0,
  candidate: {
    prompt_text: 'Synthetic Architect edited prompt.',
    model: {
      endpoint_name: 'databricks-claude-opus-4-6',
      temperature: 0.7,
      max_tokens: 60000,
      top_p: 0.95,
    },
  },
} satisfies DraftSaveRequest;

/** Complete Task 4 wire shape used by both component and browser tests. */
export const syntheticAgentDefinitionWorkbench = {
  active_release: {
    release_id: 41,
    version_number: 1,
    previous_release_id: null,
    restored_from_release_id: null,
    release_note: "Bootstrap current code-owned Agent Definitions",
    published_by: "system:bootstrap",
    published_at: "2026-09-21T12:00:00Z",
    effective_from: "2026-09-21T12:00:00Z",
    effective_to: null,
  },
  draft: {
    draft_id: 1,
    base_release_id: 41,
    base_version_number: 1,
    lock_version: 0,
    updated_by: "system:bootstrap",
    updated_at: "2026-09-21T12:00:00Z",
  },
  nodes: [
    mockModelNodes[0],
    mockModelNodes[1],
    mockModelNodes[2],
    mockModelNodes[3],
    {
      agent_key: "foreman",
      display_name: "Foreman",
      execution_kind: "deterministic",
      editable: false,
      changed: false,
      published: null,
      draft: null,
      read_only_reason: "Foreman is deterministic scheduling and routing code; it has no Agent Definition.",
    },
    mockModelNodes[4],
    mockModelNodes[5],
    mockModelNodes[6],
  ],
} satisfies AgentDefinitionWorkbenchResponse;

export function syntheticDraftSaveSuccess(
  agentKey: AgentKey,
  request: DraftSaveRequest,
  lockVersion: number,
): DraftSaveSuccessResponse {
  const definition = syntheticDraftDefinitions[agentKey];
  return {
    draft: {
      ...structuredClone(syntheticAgentDefinitionWorkbench.draft),
      lock_version: lockVersion,
      updated_by: 'admin@test.com',
      updated_at: `2026-09-22T12:00:0${lockVersion}Z`,
    },
    definition: {
      ...structuredClone(definition),
      prompt_text: request.candidate.prompt_text,
      model: structuredClone(request.candidate.model),
      candidate_hash: 'd'.repeat(64),
    },
    changed: true,
  };
}

export function syntheticDraftSaveConflict(
  request: DraftSaveRequest,
  promptEdits: Partial<Record<AgentKey, string>> = {},
  currentLockVersion = 1,
): DraftSaveConflictResponse {
  const definitions = structuredClone(syntheticDraftDefinitions);
  for (const [agentKey, promptText] of Object.entries(promptEdits) as Array<[AgentKey, string]>) {
    definitions[agentKey] = {
      ...definitions[agentKey],
      prompt_text: promptText,
      candidate_hash: 'd'.repeat(64),
    };
  }
  return {
    code: 'stale_draft',
    expected_lock_version: request.lock_version,
    current_lock_version: currentLockVersion,
    client_candidate: structuredClone(request.candidate),
    server: {
      draft: {
        ...structuredClone(syntheticAgentDefinitionWorkbench.draft),
        lock_version: currentLockVersion,
      },
      definitions,
    },
  };
}

// ============================================
// #265 protected-assembly upgrade and legacy-source fixtures
// ============================================

/** The two roles whose Graph Version 1 prompt is a protected legacy composite. */
export const LEGACY_COMPOSITE_ROLES = ['data_analyst', 'build_reviewer'] as const;

/** Exact server-authored v2 targets. The client may never derive these. */
export const V2_AUTHORED_PROMPT: Record<AgentKey, string> = {
  architect: 'Synthetic Architect authored-only v2 prompt.',
  data_analyst: 'Synthetic Data Analyst authored-only v2 prompt.',
  builder: 'Synthetic Builder authored-only v2 prompt.',
  build_reviewer: 'Synthetic Build Reviewer authored-only v2 prompt.',
  fixer: 'Synthetic Fixer authored-only v2 prompt.',
  fix_reviewer: 'Synthetic Fix Reviewer authored-only v2 prompt.',
  deck_reviewer: 'Synthetic Deck Reviewer authored-only v2 prompt.',
};

/**
 * An edited legacy prompt with a combining mark, a non-breaking space, a trailing
 * space, and a trailing newline, so byte-exact retention is observable.
 */
export const DIRTY_LEGACY_PROMPT = 'Edited énonce legacy composite \n';

/** The exact published Graph Version 1 prompt the source route returns. */
export const PUBLISHED_V1_PROMPT_SOURCE: Record<'data_analyst' | 'build_reviewer', string> = {
  data_analyst: 'Synthetic published Data Analyst Graph Version 1 composite prompt.',
  build_reviewer: 'Synthetic published Build Reviewer Graph Version 1 composite prompt.',
};

/** A definition already migrated to the v2 protected bundle and v2 rules. */
export function syntheticV2DraftDefinition(
  agentKey: AgentKey,
  overrides: Partial<DraftDefinition> = {},
): DraftDefinition {
  return {
    ...structuredClone(syntheticDraftDefinitions[agentKey]),
    prompt_text: V2_AUTHORED_PROMPT[agentKey],
    assembly_rules: structuredClone(EMPTY_V2_ASSEMBLY_RULES),
    protected_assembly: structuredClone(V2_PROTECTED_IDENTITY),
    protected_stage_view: v2ProtectedStageView(agentKey),
    candidate_hash: 'f'.repeat(64),
    ...structuredClone(overrides) as Partial<DraftDefinition>,
  };
}

/**
 * A draft definition with a v2 schema contract and one selectable optional field
 * (diagnostic_notes). Produced by a successful schema-contract-upgrade.
 */
export function syntheticSchemaV2DraftDefinition(
  agentKey: AgentKey,
  overrides: Partial<DraftDefinition> = {},
): DraftDefinition {
  return {
    ...structuredClone(syntheticDraftDefinitions[agentKey]),
    schema_contract: structuredClone(V2_SCHEMA_CONTRACT_IDENTITY),
    schema_overlay: { field_overrides: {}, additional_optional_fields: [] },
    selectable_optional_fields: [structuredClone(DIAGNOSTIC_NOTES_DESCRIPTORS[agentKey])],
    candidate_hash: '4'.repeat(64),  // valid hex (only 0-9, a-f allowed)
    ...structuredClone(overrides) as Partial<DraftDefinition>,
  };
}

/** The 200 body the schema-contract-upgrade route returns. */
export function syntheticSchemaUpgradeSuccess(
  agentKey: AgentKey,
  lockVersion: number,
  definitionOverrides: Partial<DraftDefinition> = {},
): DraftSaveSuccessResponse {
  return {
    draft: {
      ...structuredClone(syntheticAgentDefinitionWorkbench.draft),
      lock_version: lockVersion,
      updated_by: 'admin@example.com',
      updated_at: `2026-09-22T14:00:0${lockVersion}Z`,
    },
    definition: syntheticSchemaV2DraftDefinition(agentKey, definitionOverrides),
    changed: true,
  };
}

/** The 200 body the protected-assembly-upgrade route returns. */
export function syntheticUpgradeSuccess(
  agentKey: AgentKey,
  lockVersion: number,
  definitionOverrides: Partial<DraftDefinition> = {},
): DraftSaveSuccessResponse {
  return {
    draft: {
      ...structuredClone(syntheticAgentDefinitionWorkbench.draft),
      lock_version: lockVersion,
      updated_by: 'admin@example.com',
      updated_at: `2026-09-22T13:00:0${lockVersion}Z`,
    },
    definition: syntheticV2DraftDefinition(agentKey, definitionOverrides),
    changed: true,
  };
}

/**
 * A 409 for an operation that submitted no candidate. `client_candidate` is exactly
 * `null`; `v2Roles` names the roles the winning writer already moved to v2.
 */
export function syntheticNullCandidateConflict(
  expectedLockVersion: number,
  currentLockVersion: number,
  v2Roles: readonly AgentKey[] = [],
): DraftSaveConflictResponse {
  const definitions = structuredClone(syntheticDraftDefinitions);
  for (const agentKey of v2Roles) definitions[agentKey] = syntheticV2DraftDefinition(agentKey);
  return {
    code: 'stale_draft',
    expected_lock_version: expectedLockVersion,
    current_lock_version: currentLockVersion,
    client_candidate: null,
    server: {
      draft: {
        ...structuredClone(syntheticAgentDefinitionWorkbench.draft),
        lock_version: currentLockVersion,
      },
      definitions,
    },
  };
}

/** The 200 body the legacy-prompt-source route returns; this route never writes. */
export function syntheticLegacyPromptSource(
  agentKey: 'data_analyst' | 'build_reviewer',
  lockVersion = 0,
): LegacyPromptSourceResponse {
  return {
    draft: {
      ...structuredClone(syntheticAgentDefinitionWorkbench.draft),
      lock_version: lockVersion,
    },
    agent_key: agentKey,
    lock_version: lockVersion,
    source: {
      prompt_text: PUBLISHED_V1_PROMPT_SOURCE[agentKey],
      revision_id: 12,
      content_hash: 'a'.repeat(64),
    },
  };
}

/** The exact ordered 422 the upgrade route returns for an edited legacy prompt. */
export const MANUAL_RESOLUTION_REJECTION: DraftValidationErrorResponse = {
  code: 'invalid_draft',
  errors: [
    {
      field: 'prompt_text',
      code: 'legacy_prompt_manual_resolution_required',
      message: 'Legacy protected prompt content was edited. Restore the exact Graph Version 1 '
        + 'prompt before upgrading, then reapply authored edits.',
    },
  ],
};

/** The exact ordered 422 the upgrade route returns for an already-current draft. */
export const ALREADY_CURRENT_REJECTION: DraftValidationErrorResponse = {
  code: 'invalid_draft',
  errors: [
    {
      field: 'protected_assembly.version',
      code: 'already_current',
      message: 'Protected assembly is already current.',
    },
  ],
};

// ============================================================
// #266 model endpoint discovery (GET /api/admin/agent-definitions/model-endpoints)
// ============================================================

/** The exact seed endpoint every packaged role starts on. */
export const SEED_MODEL_ENDPOINT_NAME = 'databricks-claude-opus-4-6';

/**
 * A populated discovery list in backend order. The second item's display name differs
 * from its exact name, and the third keeps an exotic spelling with spaces, so a client
 * that selects anything but `name` byte-for-byte is observable.
 */
export const syntheticSystemModelEndpoints: SystemModelEndpoint[] = [
  {
    name: 'databricks-claude-opus-4-6',
    display_name: 'Claude Opus 4.6',
    description: 'Synthetic frontier chat model.',
    docs: 'https://docs.example.invalid/claude-opus-4-6',
  },
  {
    name: 'databricks-gpt-oss-120b',
    display_name: 'GPT OSS 120B',
    description: 'Synthetic open-weight chat model.',
    docs: null,
  },
  {
    name: 'Team Shared Endpoint (EU)',
    display_name: null,
    description: null,
    docs: null,
  },
];

/** A newer family member that a refresh may expose; it must never move the seed. */
export const syntheticNewerModelEndpoint: SystemModelEndpoint = {
  name: 'databricks-claude-opus-4-7',
  display_name: 'Claude Opus 4.7',
  description: 'Synthetic newer frontier chat model.',
  docs: 'https://docs.example.invalid/claude-opus-4-7',
};

export function syntheticModelEndpointDiscovery(
  items: SystemModelEndpoint[] = syntheticSystemModelEndpoints,
): { items: SystemModelEndpoint[] } {
  return { items: structuredClone(items) };
}

/** The exact 403 envelope the discovery route returns for a forbidden identity. */
export const MODEL_ENDPOINT_DISCOVERY_FORBIDDEN = {
  code: 'catalog_forbidden',
  message: 'Model endpoint discovery is not permitted with this workspace identity.',
  retryable: false,
} as const;

/** The exact 503 envelope the discovery route returns when the catalog is unavailable. */
export const MODEL_ENDPOINT_DISCOVERY_UNAVAILABLE = {
  code: 'catalog_unavailable',
  message: 'Model endpoint discovery is temporarily unavailable. Retry the request.',
  retryable: true,
} as const;

/**
 * The one endpoint-name policy case table (#266). The client policy table in
 * `AgentDefinitionWorkbench.test.tsx` drives `validateDraftForm` with it, and
 * `tests/unit/test_endpoint_name_policy_client_join.py` reads this block as text and
 * drives the server's `validate_endpoint_name_policy` with the same cases. Keep the
 * body strict JSON (double quotes, no trailing commas, no comments).
 */
export const ENDPOINT_NAME_POLICY_CASES: Record<'rejected' | 'accepted', string[]> = {
  "rejected": [
    "https://example.cloud.databricks.com/serving-endpoints/x/invocations",
    "  http://example.invalid",
    "//example.invalid/x",
    "ftp://example.invalid",
    "a/b",
    "a\\b",
    "x?y=1",
    "x#frag",
    "a%2Fb",
    ".",
    "..",
    "tab\tname",
    "nul\u0000name",
    "unit\u001fsep",
    "del\u007fname"
  ],
  "accepted": [
    "databricks-claude-opus-4-6",
    "Team Shared Endpoint (EU)",
    " leading and trailing ",
    "a.b",
    "...",
    "mailto:x",
    "ünïcode-endpoint"
  ]
};

// ============================================================
// #266 saved-candidate structured-output probe
// (POST /api/admin/agent-definitions/draft/{agent_key}/model-endpoint-probe)
// ============================================================

/** The exact seed identity every packaged role's saved candidate starts on. */
export const SEED_CANDIDATE_HASH = 'a'.repeat(64);

/**
 * The server's code-owned probe failure table, verbatim from
 * `src/services/model_endpoint_probe.py` and the route's status map (#266 Task 5
 * ruling): forbidden 403 and unsupported 422 are not retryable; only the ambiguous
 * 503 is.
 */
export const STRUCTURED_OUTPUT_PROBE_FAILURES = {
  unsupported_structured_output: {
    status: 422,
    message: 'The endpoint rejected the structured-output test request.',
    retryable: false,
  },
  endpoint_probe_forbidden: {
    status: 403,
    message: 'The app is not permitted to query this endpoint.',
    retryable: false,
  },
  structured_output_probe_failed: {
    status: 503,
    message: 'The structured output probe could not complete. Retry the probe.',
    retryable: true,
  },
} as const;

export type StructuredOutputProbeFailureFixtureCode = keyof typeof STRUCTURED_OUTPUT_PROBE_FAILURES;

export interface StructuredOutputProbeIdentityFixture {
  endpoint_name: string;
  candidate_hash: string;
  lock_version: number;
}

function probeIdentity(
  identity: Partial<StructuredOutputProbeIdentityFixture>,
): StructuredOutputProbeIdentityFixture {
  return {
    endpoint_name: identity.endpoint_name ?? SEED_MODEL_ENDPOINT_NAME,
    candidate_hash: identity.candidate_hash ?? SEED_CANDIDATE_HASH,
    lock_version: identity.lock_version ?? 0,
  };
}

/** The exact 200 body: the identity of the saved candidate the probe ran against. */
export function syntheticProbeSuccess(identity: Partial<StructuredOutputProbeIdentityFixture> = {}) {
  return { code: 'structured_output_probe_succeeded' as const, ...probeIdentity(identity) };
}

/** The exact typed failure body for one code; its status is `STRUCTURED_OUTPUT_PROBE_FAILURES[code].status`. */
export function syntheticProbeFailure(
  code: StructuredOutputProbeFailureFixtureCode,
  identity: Partial<StructuredOutputProbeIdentityFixture> = {},
) {
  const failure = STRUCTURED_OUTPUT_PROBE_FAILURES[code];
  return { code, message: failure.message, retryable: failure.retryable, ...probeIdentity(identity) };
}

// ============================================================
// #267 Agent Test Cases and Test Runs
// ============================================================
// Appended last, and every new name is a function or a constant that begins with no
// existing exported name (the Python joins find blocks with `index("export const X")`).

/** One active Agent Test Case version exactly as `GET /test-cases` serializes it. */
export function syntheticAgentTestCase(overrides: Partial<TestCaseListEntry> = {}): TestCaseListEntry {
  return {
    id: 101,
    agent_key: 'architect',
    name: 'Architect quarterly revenue outline',
    version: 1,
    is_active: true,
    is_required: true,
    synthetic_payload: {
      user_request: 'Outline a five-slide quarterly revenue review for a fictional retailer.',
      session_id: 'synthetic-session-0001',
    },
    assembly_context: { design_system_active: false },
    created_by: 'system:bootstrap',
    created_at: '2026-09-21T12:00:00Z',
    updated_by: 'system:bootstrap',
    updated_at: '2026-09-21T12:00:00Z',
    is_synthetic_data_warning: true,
    ...overrides,
  };
}

/** The exact list body for `GET /test-cases?agent_key=<role>`. */
export function syntheticAgentTestCaseList(items: TestCaseListEntry[] = [syntheticAgentTestCase()]) {
  return { items };
}

/**
 * One persisted run exactly as the execute routes serialize it: an execute response
 * carries boolean currency flags, and no verdict field exists (#268 adds verdicts).
 */
export function syntheticTestRunEvidence(overrides: Partial<TestRunEvidence> = {}): TestRunEvidence {
  return {
    run_id: 501,
    run_kind: 'candidate',
    test_case_id: 101,
    test_case_version: 1,
    agent_key: 'architect',
    candidate_hash: 'a'.repeat(64),
    compared_release_id: 41,
    compared_definition_revision_id: 11,
    synthetic_payload: {
      user_request: 'Outline a five-slide quarterly revenue review for a fictional retailer.',
      session_id: 'synthetic-session-0001',
    },
    model_payload: {
      user_request: 'Outline a five-slide quarterly revenue review for a fictional retailer.',
    },
    assembled_prompt: 'Synthetic assembled Architect prompt for the saved candidate.',
    execution_status: 'completed',
    error_detail: null,
    deterministic_checks_passed: true,
    deterministic_check_results: [
      { name: 'execution', passed: true, message: null, issues: [] },
      { name: 'output_contract', passed: true, message: null, issues: [] },
    ],
    candidate_raw_output: { title: 'Synthetic candidate raw title' },
    candidate_structured_output: { title: 'Synthetic candidate structured title' },
    baseline_raw_output: null,
    baseline_structured_output: null,
    latency_ms: 812.5,
    input_tokens: null,
    output_tokens: null,
    run_by: 'admin@test.com',
    run_at: '2026-09-26T10:00:00Z',
    candidate_is_current: true,
    base_release_is_current: true,
    ...overrides,
  };
}

/** The route's exact 503 body: no row was written, and the request may be retried. */
export function syntheticTestRunUnavailable() {
  return {
    code: 'test_run_unavailable' as const,
    message: 'Test run storage is temporarily unavailable. Retry the request.',
    retryable: true as const,
  };
}

/** The exact 409 body for a superseded or retired case version (Task 2's envelope). */
export function syntheticStaleTestCase(testCaseId = 101) {
  return {
    code: 'stale_test_case' as const,
    test_case_id: testCaseId,
    message: 'This test case version is no longer active. Reload and retry.',
  };
}

/** The exact ordered 422 envelope for a refused case write or a role-mismatched run. */
export function syntheticInvalidTestCase(issues: Array<{ field: string; code: string; message: string }>) {
  return { code: 'invalid_test_case' as const, issues };
}
