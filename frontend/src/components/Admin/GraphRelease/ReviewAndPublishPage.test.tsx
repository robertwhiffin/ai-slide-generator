import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  RELEASE_ARCHITECT_CANDIDATE_HASH,
  syntheticAgentReadiness,
  syntheticChangedDefinition,
  syntheticDraftReadinessBody,
  syntheticNothingToPublish,
  syntheticPublicationInvalid,
  syntheticPublicationNotReady,
  syntheticPublishSuccess,
  syntheticPublishedReleasePreview,
  syntheticReleasePreview,
  syntheticStalePublication,
  syntheticTestCaseReadiness,
} from '../../../../tests/fixtures/mocks';
import type { ReleasePreviewResponse } from '../../../api/agentDefinitions';
import { ReviewAndPublishPage } from './ReviewAndPublishPage';

const PREVIEW_URL = /\/api\/admin\/agent-definitions\/release-preview$/;
const RELEASES_URL = /\/api\/admin\/agent-definitions\/releases$/;

function apiResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: vi.fn().mockResolvedValue(body),
  };
}

type Responder = () => Promise<unknown> | unknown;

/**
 * Routes by URL and method. Each queue answers in order and repeats its last answer; any
 * other request throws, so nothing can be answered with the wrong body.
 */
function mockReleaseApi({ previews, publishes = [] }: { previews: Responder[]; publishes?: Responder[] }) {
  let previewCall = 0;
  let publishCall = 0;
  const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (PREVIEW_URL.test(url) && init?.method === 'GET') {
      return previews[Math.min(previewCall++, previews.length - 1)]();
    }
    if (RELEASES_URL.test(url) && init?.method === 'POST') {
      if (publishes.length === 0) throw new Error('unexpected publish POST');
      return publishes[Math.min(publishCall++, publishes.length - 1)]();
    }
    throw new Error(`unexpected request ${init?.method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function previewOf(body: ReleasePreviewResponse = syntheticReleasePreview()): Responder {
  return () => apiResponse(200, body);
}

function previewGets(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter(([url, init]) => PREVIEW_URL.test(String(url)) && (init as RequestInit).method === 'GET');
}

function publishPosts(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter(([url, init]) => RELEASES_URL.test(String(url)) && (init as RequestInit).method === 'POST');
}

async function loadedPage() {
  const page = await screen.findByTestId('release-review-page');
  await screen.findByTestId('release-next-version');
  return page;
}

function publishButton() {
  return screen.getByTestId('release-publish-button');
}

function typeNote(note: string) {
  fireEvent.change(screen.getByTestId('release-note-input'), { target: { value: note } });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('ReviewAndPublishPage: the preview', () => {
  it('shows the title, the next Graph Version, the draft base and the Publish label', async () => {
    const fetchMock = mockReleaseApi({ previews: [previewOf()] });
    render(<ReviewAndPublishPage />);

    await loadedPage();
    expect(screen.getByRole('heading', { level: 1, name: 'Review & Publish' })).toBeInTheDocument();
    expect(screen.getByTestId('release-next-version')).toHaveTextContent('Next Graph Version: 2');
    expect(screen.getByText('Draft base: Graph Version 1')).toBeInTheDocument();
    expect(publishButton()).toHaveAccessibleName('Publish Graph Version 2');
    expect(previewGets(fetchMock)).toHaveLength(1);
    expect(publishPosts(fetchMock)).toHaveLength(0);
  });

  it('lists every changed role with each required case\'s readiness label (Correction 54)', async () => {
    const statuses = ['needs_test', 'test_failed', 'awaiting_review', 'approved'] as const;
    const preview = syntheticReleasePreview({
      changed: [
        syntheticChangedDefinition('architect'),
        syntheticChangedDefinition('builder', { field_diffs: [{ field: 'model.max_tokens', published: 4096, candidate: 8192 }] }),
      ],
      publishable: false,
      readiness: syntheticDraftReadinessBody({
        draft_lock_version: 3,
        all_ready: false,
        blocking_agents: ['architect', 'builder'],
        agents: {
          architect: syntheticAgentReadiness('architect', {
            candidate_hash: RELEASE_ARCHITECT_CANDIDATE_HASH,
            is_changed_from_base: true,
            ready: false,
            cases: statuses.map((status, index) => syntheticTestCaseReadiness({
              test_case_id: 101 + index,
              test_case_name: `Architect case ${index + 1}`,
              status,
            })),
          }),
          builder: syntheticAgentReadiness('builder', {
            is_changed_from_base: true,
            ready: false,
            missing_required_case: true,
          }),
        },
      }),
    });
    mockReleaseApi({ previews: [previewOf(preview)] });
    render(<ReviewAndPublishPage />);
    await loadedPage();

    const architect = screen.getByRole('region', { name: 'Architect' });
    expect(within(architect).getByText('Architect case 1: Needs test')).toBeInTheDocument();
    expect(within(architect).getByText('Architect case 2: Test failed')).toBeInTheDocument();
    expect(within(architect).getByText('Architect case 3: Awaiting review')).toBeInTheDocument();
    expect(within(architect).getByText('Architect case 4: Approved')).toBeInTheDocument();
    expect(within(architect).getByText('Changed fields: prompt_text, model.temperature')).toBeInTheDocument();
    const builder = screen.getByRole('region', { name: 'Builder' });
    expect(within(builder).getByText('No active required test case')).toBeInTheDocument();
    expect(within(builder).getByText('Changed fields: model.max_tokens')).toBeInTheDocument();
    // Only changed roles are listed, and no raw readiness code is shown.
    expect(screen.queryByRole('region', { name: 'Fixer' })).not.toBeInTheDocument();
    expect(screen.getByTestId('release-review-page')).not.toHaveTextContent('awaiting_review');
  });

  it('shows the field diffs per role on the Definition Diff tab, prompts line by line', async () => {
    mockReleaseApi({ previews: [previewOf()] });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    expect(screen.getByTestId('release-changes-tab')).toHaveAttribute('aria-selected', 'true');

    fireEvent.click(screen.getByTestId('release-diff-tab'));

    expect(screen.getByTestId('release-diff-tab')).toHaveAttribute('aria-selected', 'true');
    const architect = screen.getByRole('region', { name: 'Architect diff' });
    const prompt = within(architect).getByRole('list', { name: 'prompt_text' });
    expect(within(prompt).getAllByRole('listitem').map((item) => [item.dataset.kind, item.textContent])).toEqual([
      ['same', '  Plan the deck.'],
      ['removed', '- Use three sections.'],
      ['added', '+ Use four sections.'],
      ['same', '  Cite sources.'],
    ]);
    expect(within(architect).getByTestId('release-diff-model.temperature')).toHaveTextContent('0.2 → 0.4');
  });

  it('renders prompt text as text, never as markup', async () => {
    const preview = syntheticReleasePreview({
      changed: [syntheticChangedDefinition('architect', {
        field_diffs: [{ field: 'prompt_text', published: 'safe', candidate: '<img src=x onerror="alert(1)">' }],
      })],
    });
    mockReleaseApi({ previews: [previewOf(preview)] });
    const { container } = render(<ReviewAndPublishPage />);
    await loadedPage();
    fireEvent.click(screen.getByTestId('release-diff-tab'));

    expect(screen.getByText('+ <img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
  });

  it('says so when nothing changed, and Publish stays disabled', async () => {
    mockReleaseApi({ previews: [previewOf(syntheticPublishedReleasePreview())] });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    typeNote('A note');

    expect(screen.getByText('No Agent Definitions changed since Graph Version 2.')).toBeInTheDocument();
    expect(publishButton()).toBeDisabled();
  });

  it('shows a failed preview read as an alert with Reload preview', async () => {
    const fetchMock = mockReleaseApi({ previews: [() => apiResponse(500, { detail: 'boom' }), previewOf()] });
    render(<ReviewAndPublishPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load the release preview (500).');
    fireEvent.click(screen.getByRole('button', { name: 'Reload preview' }));

    await loadedPage();
    expect(previewGets(fetchMock)).toHaveLength(2);
  });

  // #270 Correction 4: the one deliberate edit to this #269 test. The absence of any
  // history or rollback control became exactly three tabs, in order.
  it('offers exactly three tabs, in order, and no rollback control before Release History opens', async () => {
    const fetchMock = mockReleaseApi({ previews: [previewOf()] });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    typeNote('A note');

    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Changes & Approvals',
      'Definition Diff',
      'Release History',
    ]);
    const names = [...screen.queryAllByRole('button'), ...screen.queryAllByRole('link')]
      .map((control) => control.textContent ?? '');
    expect(names.filter((name) => /rollback|roll back/i.test(name))).toEqual([]);
    // The history is read only when its tab is opened.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('ReviewAndPublishPage: the Publish button (Correction 22)', () => {
  it.each(['', '   '])('is disabled with the blank note %j', async (note) => {
    mockReleaseApi({ previews: [previewOf()] });
    render(<ReviewAndPublishPage />);
    await loadedPage();

    typeNote(note);

    expect(publishButton()).toBeDisabled();
    expect(screen.getByText('Enter a release note to publish.')).toBeInTheDocument();
  });

  it('is disabled with blocking readiness (the server\'s publishable=false), whatever the note', async () => {
    mockReleaseApi({ previews: [previewOf(syntheticReleasePreview({
      publishable: false,
      readiness: syntheticPublicationNotReady().readiness,
    }))] });
    render(<ReviewAndPublishPage />);
    await loadedPage();

    typeNote('A complete release note');

    expect(publishButton()).toBeDisabled();
    expect(screen.getByText('This draft cannot be published yet.')).toBeInTheDocument();
  });

  it('is enabled by the server\'s publishable=true even when readiness reads blocking (C32: informational)', async () => {
    mockReleaseApi({ previews: [previewOf(syntheticReleasePreview({
      readiness: syntheticPublicationNotReady().readiness,
    }))] });
    render(<ReviewAndPublishPage />);
    await loadedPage();

    typeNote('A complete release note');

    expect(publishButton()).toBeEnabled();
  });

  it('is disabled above 2000 characters', async () => {
    mockReleaseApi({ previews: [previewOf()] });
    render(<ReviewAndPublishPage />);
    await loadedPage();

    typeNote('x'.repeat(2000));
    expect(publishButton()).toBeEnabled();
    expect(screen.getByText('2000 / 2000')).toBeInTheDocument();
    typeNote('x'.repeat(2001));
    expect(publishButton()).toBeDisabled();
  });

  it('counts code points, as the server does: 2000 astral characters fill the cap and still publish (m1)', async () => {
    mockReleaseApi({ previews: [previewOf()] });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    const astral = '\u{1F680}'.repeat(2000);
    expect(astral.length).toBe(4000);

    typeNote(astral);

    expect(screen.getByText('2000 / 2000')).toBeInTheDocument();
    expect(publishButton()).toBeEnabled();
  });

  it('sends exactly one POST per click, with the previewed lock and the typed note', async () => {
    let settle: (value: unknown) => void = () => {};
    const fetchMock = mockReleaseApi({
      previews: [previewOf(), previewOf(syntheticPublishedReleasePreview())],
      publishes: [() => new Promise((resolve) => { settle = resolve; })],
    });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    typeNote('Tighten the outline');
    const button = publishButton();

    // Two clicks inside one act share one render: only the in-flight gate stops the second.
    act(() => {
      fireEvent.click(button);
      fireEvent.click(button);
    });
    fireEvent.click(button);

    expect(publishPosts(fetchMock)).toHaveLength(1);
    expect(publishPosts(fetchMock)[0][1].body).toBe('{"lock_version":3,"release_note":"Tighten the outline"}');
    expect(button).toBeDisabled();
    expect(screen.getByTestId('release-note-input')).toHaveAttribute('readonly');
    await act(async () => settle(apiResponse(200, syntheticPublishSuccess())));
    await screen.findByTestId('release-success-panel');
    expect(publishPosts(fetchMock)).toHaveLength(1);
  });
});

describe('ReviewAndPublishPage: publication outcomes', () => {
  it('shows the success panel and refetches the preview exactly once', async () => {
    const fetchMock = mockReleaseApi({
      previews: [previewOf(), previewOf(syntheticPublishedReleasePreview())],
      publishes: [() => apiResponse(200, syntheticPublishSuccess())],
    });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    typeNote('Tighten the outline');

    fireEvent.click(publishButton());

    const success = await screen.findByTestId('release-success-panel');
    expect(success).toHaveTextContent('Published Graph Version 2');
    expect(success).toHaveTextContent('The shared draft is now based on Graph Version 2');
    await screen.findByText('Draft base: Graph Version 2');
    expect(screen.getByText('No Agent Definitions changed since Graph Version 2.')).toBeInTheDocument();
    expect(previewGets(fetchMock)).toHaveLength(2);
    expect(publishPosts(fetchMock)).toHaveLength(1);
    expect(publishButton()).toBeDisabled();
    // Settle any stray effect before counting again.
    await act(async () => {});
    expect(previewGets(fetchMock)).toHaveLength(2);
  });

  it('recovers a failed post-publish refetch through Reload preview (m2)', async () => {
    const fetchMock = mockReleaseApi({
      previews: [previewOf(), () => apiResponse(500, { detail: 'boom' }), previewOf(syntheticPublishedReleasePreview())],
      publishes: [() => apiResponse(200, syntheticPublishSuccess())],
    });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    typeNote('Tighten the outline');

    fireEvent.click(publishButton());

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Unable to load the release preview (500).');
    // The publication itself is still reported.
    expect(screen.getByTestId('release-success-panel')).toHaveTextContent('Published Graph Version 2');
    expect(previewGets(fetchMock)).toHaveLength(2);

    fireEvent.click(within(alert).getByRole('button', { name: 'Reload preview' }));

    await screen.findByText('Draft base: Graph Version 2');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('No Agent Definitions changed since Graph Version 2.')).toBeInTheDocument();
    expect(previewGets(fetchMock)).toHaveLength(3);
    expect(publishPosts(fetchMock)).toHaveLength(1);
  });

  it('keeps the note on a stale 409 and never retries until Reload preview, which reads once', async () => {
    const fetchMock = mockReleaseApi({
      previews: [previewOf(), previewOf(syntheticReleasePreview({ draft: syntheticStalePublication().draft }))],
      publishes: [() => apiResponse(409, syntheticStalePublication())],
    });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    typeNote('My careful note');

    fireEvent.click(publishButton());

    const alert = await screen.findByTestId('release-stale-alert');
    expect(alert).toHaveTextContent('lock version 5');
    expect(alert).toHaveTextContent('Graph Version 1 is active');
    expect(screen.getByTestId('release-note-input')).toHaveValue('My careful note');
    expect(publishButton()).toBeDisabled();
    await act(async () => {});
    expect(publishPosts(fetchMock)).toHaveLength(1);
    expect(previewGets(fetchMock)).toHaveLength(1);

    fireEvent.click(within(alert).getByRole('button', { name: 'Reload preview' }));

    await screen.findByText('Lock version: 5');
    expect(screen.queryByTestId('release-stale-alert')).not.toBeInTheDocument();
    expect(previewGets(fetchMock)).toHaveLength(2);
    expect(publishPosts(fetchMock)).toHaveLength(1);
    expect(screen.getByTestId('release-note-input')).toHaveValue('My careful note');
    expect(publishButton()).toBeEnabled();
  });

  it('lists the not-ready gaps, labelling both codes on the client', async () => {
    mockReleaseApi({
      previews: [previewOf()],
      publishes: [() => apiResponse(409, syntheticPublicationNotReady([
        { agent_key: 'architect', test_case_id: 101, code: 'no_eligible_approval' },
        { agent_key: 'builder', test_case_id: null, code: 'no_required_case' },
      ]))],
    });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    typeNote('A note');

    fireEvent.click(publishButton());

    const panel = await screen.findByTestId('release-not-ready-panel');
    expect(within(panel).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Architect: Architect quarterly revenue outline has no eligible approval',
      'Builder: no active required test case',
    ]);
    expect(within(panel).getByRole('button', { name: 'Reload preview' })).toBeInTheDocument();
    expect(screen.getByTestId('release-note-input')).toHaveValue('A note');
  });

  it('says there is nothing to publish on that 409', async () => {
    mockReleaseApi({ previews: [previewOf()], publishes: [() => apiResponse(409, syntheticNothingToPublish())] });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    typeNote('A note');

    fireEvent.click(publishButton());

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Nothing to publish: the shared draft matches Graph Version 1.',
    );
  });

  it('shows the 422 note error beside the textarea, by code, and clears it on edit', async () => {
    mockReleaseApi({ previews: [previewOf()], publishes: [() => apiResponse(422, syntheticPublicationInvalid())] });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    // JavaScript trims this, Python's str.strip removes it: only the server sees it blank.
    typeNote('\u001f');

    fireEvent.click(publishButton());

    const error = await screen.findByText('Enter a release note.');
    const textarea = screen.getByTestId('release-note-input');
    expect(textarea).toHaveAttribute('aria-invalid', 'true');
    expect(textarea).toHaveAccessibleDescription(expect.stringContaining('Enter a release note.'));
    expect(error.id).toBe('release-note-error');
    expect(publishButton()).toBeDisabled();

    typeNote('A real note');
    expect(screen.queryByText('Enter a release note.')).not.toBeInTheDocument();
    expect(publishButton()).toBeEnabled();
  });

  it('never shows the Pydantic message of a malformed-body 422', async () => {
    mockReleaseApi({ previews: [previewOf()], publishes: [() => apiResponse(422, syntheticPublicationInvalid([{
      field: '$', code: 'strict_type', message: 'Input should be a valid dictionary or instance of PublishReleaseRequest',
    }]))] });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    typeNote('A note');

    fireEvent.click(publishButton());

    expect(await screen.findByText('The publish request was refused.')).toBeInTheDocument();
    expect(screen.getByTestId('release-review-page')).not.toHaveTextContent('PublishReleaseRequest');
  });

  it('shows a malformed publish response as an error without retrying', async () => {
    const fetchMock = mockReleaseApi({ previews: [previewOf()], publishes: [() => apiResponse(409, { code: 'stale_publication' })] });
    render(<ReviewAndPublishPage />);
    await loadedPage();
    typeNote('A note');

    fireEvent.click(publishButton());

    expect(await screen.findByRole('alert')).toHaveTextContent('The server returned an invalid publication response.');
    expect(publishPosts(fetchMock)).toHaveLength(1);
  });
});
