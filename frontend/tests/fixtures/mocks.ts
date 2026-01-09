/**
 * Mock data for API responses based on observed network traffic.
 * These mocks simulate the backend responses for testing.
 */

// Profiles endpoint returns an array directly
export const mockProfiles = [
  {
    id: 1,
    name: "KPMG UK Consumption",
    description: "Claude 4.5 and kpmg uk consumption data",
    is_default: true,
    created_at: "2026-01-08T20:10:29.720015",
    created_by: "system",
    updated_at: "2026-01-08T20:10:29.720025",
    updated_by: null
  },
  {
    id: 2,
    name: "use cases",
    description: "Use case analysis and progression tracking",
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
      name: "Consumption Review",
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
      name: "Databricks Brand",
      description: "Official Databricks brand colors and typography. Navy headers, Lava red accents, clean modern layout.",
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
      title: "Session 2026-01-08 20:38",
      created_at: "2026-01-08T20:38:56.749592",
      last_activity: "2026-01-08T20:42:11.058737",
      message_count: 4,
      has_slide_deck: true,
      profile_id: 1,
      profile_name: "KPMG UK Consumption"
    },
    {
      session_id: "a2c5f1d9-8ef7-48dc-be69-0ead7be316dd",
      user_id: null,
      title: "Session 2026-01-08 20:20",
      created_at: "2026-01-08T20:20:26.292382",
      last_activity: "2026-01-08T20:21:02.581630",
      message_count: 4,
      has_slide_deck: true,
      profile_id: 2,
      profile_name: "use cases"
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
