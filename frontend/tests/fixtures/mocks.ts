/**
 * Mock data for API responses based on observed network traffic.
 * These mocks simulate the backend responses for testing.
 */

// Profiles endpoint returns an array directly
export const mockProfiles = [
  {
    id: 1,
    name: "Sales Analytics",
    description: "Analytics profile for sales data insights",
    is_default: true,
    created_at: "2026-01-08T20:10:29.720015",
    created_by: "system",
    updated_at: "2026-01-08T20:10:29.720025",
    updated_by: null
  },
  {
    id: 2,
    name: "Marketing Reports",
    description: "Marketing campaign performance reports",
    is_default: false,
    created_at: "2026-01-08T20:10:29.724407",
    created_by: "system",
    updated_at: "2026-01-08T20:10:29.724411",
    updated_by: null
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
      created_by: "system",
      created_at: "2026-01-08T20:10:28.695640",
      updated_by: "system",
      updated_at: "2026-01-08T20:10:28.695641"
    }
  ],
  total: 2
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
// Profile Operation Mocks
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
