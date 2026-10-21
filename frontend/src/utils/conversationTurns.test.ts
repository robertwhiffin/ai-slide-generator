/**
 * #317 Task 6: conversation turns in the chat panel.
 *
 * `withoutTurn(messages, userMessageId)` drops one turn locally after a successful delete: the user
 * message with that id and every message after it up to (not including) the next user message,
 * the same span the backend deletes. `withPersistedUserIds(panel, persisted)` gives the panel's
 * id-less user messages (a just-sent message is shown before its row exists) the ids of the
 * persisted user rows they are, by identical content, pairing from the newest (plan D12), and
 * never pairing content shared by more id-less messages than unclaimed rows (whole-branch W1).
 *
 * Every expectation is the whole resulting array, so an implementation that passes these tests
 * removes or identifies exactly the right messages.
 *
 * SABOTAGE:
 *   - withoutTurn stops at the first non-assistant message instead of the next user message
 *                                                      -> "a tool message ... is removed with it" RED.
 *   - withoutTurn matches any role carrying the id    -> "only a user message starts a turn" RED.
 *   - withPersistedUserIds pairs from the oldest      -> "1 — assigns ids ..." RED.
 *   - drop the ambiguity skip (W1)                    -> "2", "2b", "2c" RED (and ChatPanel's
 *                                                         "a refused duplicate send ..." RED).
 *   - skip every content once any is ambiguous        -> "2c — only the ambiguous content ..." RED.
 *   - drop the `taken` check                          -> "4 — ... (an assistant message carries the id)" RED.
 *   - drop the `floor` bound                          -> "9 — a row older than ..." RED.
 *   - drop the `limit` bound                          -> "9b — a row newer than ..." RED.
 *   - pair rows without a numeric id                  -> "5 — rows without a numeric id" RED.
 *   - pair by prefix / inclusion, not equality        -> "6 — ... image-injected text" RED.
 *   - pair every role, not only user messages         -> "7 — assistant messages ..." RED.
 *   - always return a copy                            -> "8 — ... returns `panel` itself" RED.
 *   - do not lower `limit` after a pairing            -> "10 — ... in panel order" RED.
 *   - match content ignoring whitespace or case       -> "6b — ... differs only in whitespace or case" RED.
 */
import { describe, expect, it } from 'vitest';
import { withoutTurn, withPersistedUserIds } from './conversationTurns';
import type { Message } from '../types/message';
import type { SessionMessage } from '../services/api';

const T = '2026-10-20T10:00:00.000Z';

function user(content: string, id?: number): Message {
  return id === undefined ? { role: 'user', content, timestamp: T } : { id, role: 'user', content, timestamp: T };
}

function assistant(content: string, id?: number): Message {
  return id === undefined
    ? { role: 'assistant', content, timestamp: T }
    : { id, role: 'assistant', content, timestamp: T };
}

function row(id: number, role: SessionMessage['role'], content: string): SessionMessage {
  return { id, role, content, message_type: role === 'user' ? 'chat' : 'llm_response', created_at: T };
}

/** A deep copy, to prove a helper never mutates its input. */
function snapshot<V>(value: V): V {
  return structuredClone(value);
}

describe('withoutTurn', () => {
  it('removes the user message and every message up to the next user message', () => {
    const messages = [
      user('first', 1),
      assistant('reply to first', 2),
      user('second', 3),
      assistant('working on it', 4),
      assistant('done with second', 5),
      user('third', 6),
      assistant('reply to third', 7),
    ];
    const before = snapshot(messages);

    const result = withoutTurn(messages, 3);

    expect(result).toEqual([messages[0], messages[1], messages[5], messages[6]]);
    expect(messages).toEqual(before);
  });

  it('a tool message and a tool-call assistant message inside the turn are removed with it (F9)', () => {
    const messages: Message[] = [
      user('first', 1),
      assistant('reply to first', 2),
      user('use the sales table', 3),
      {
        id: 4,
        role: 'assistant',
        content: '',
        timestamp: T,
        tool_call: { name: 'query_genie_space', arguments: { query: 'sales by region' } },
      },
      { id: 5, role: 'tool', content: '{"rows": 12}', timestamp: T, tool_call_id: 'call-1' },
      assistant('Here are the sales slides.', 6),
      user('third', 7),
      assistant('reply to third', 8),
    ];

    const result = withoutTurn(messages, 3);

    expect(result).toEqual([messages[0], messages[1], messages[6], messages[7]]);
  });

  it('the last turn runs to the end of the conversation', () => {
    const messages = [
      user('first', 1),
      assistant('reply to first', 2),
      user('last', 3),
      assistant('working', 4),
      assistant('done', 5),
    ];

    expect(withoutTurn(messages, 3)).toEqual([messages[0], messages[1]]);
  });

  it('assistant messages before the first user message are never removed', () => {
    const messages = [
      assistant('Welcome! What deck shall we build?', 1),
      assistant('Tip: attach a Genie space for data.', 2),
      user('first', 3),
      assistant('reply to first', 4),
      user('second', 5),
      assistant('reply to second', 6),
    ];

    expect(withoutTurn(messages, 3)).toEqual([messages[0], messages[1], messages[4], messages[5]]);
  });

  it('an unknown id returns the same array', () => {
    const messages = [user('first', 1), assistant('reply', 2)];

    expect(withoutTurn(messages, 99)).toBe(messages);
  });

  it('a message without an id is never matched', () => {
    // An id-less user message with the same text sits before the identified one; only the
    // identified one's turn goes.
    const messages = [
      user('try again'),
      assistant('Something went wrong.'),
      user('try again', 7),
      assistant('Done.', 8),
    ];

    expect(withoutTurn(messages, 7)).toEqual([messages[0], messages[1]]);

    const idless = [user('hello'), assistant('hi')];
    expect(withoutTurn(idless, 1)).toBe(idless);
  });

  it('only a user message starts a turn: an assistant message carrying the id is not matched', () => {
    const messages = [user('first', 1), assistant('reply', 2), user('second', 3), assistant('reply 2', 4)];

    expect(withoutTurn(messages, 2)).toBe(messages);
  });
});

describe('withPersistedUserIds', () => {
  it('1 — assigns ids to id-less user messages by identical content, in order (two stored copies, two rows: both pair)', () => {
    const panel = [
      user('Build a deck about puffins'),
      assistant('Here is a plan.'),
      user('yes'),
      assistant('Building 3 slides.'),
      user('yes'),
      assistant('Done.'),
    ];
    const rows = [
      row(1, 'user', 'Build a deck about puffins'),
      row(2, 'assistant', 'Here is a plan.'),
      row(3, 'user', 'yes'),
      row(4, 'assistant', 'Done building.'),
      row(5, 'user', 'yes'),
      row(6, 'assistant', 'Done.'),
    ];

    const result = withPersistedUserIds(panel, rows);

    expect(result).toEqual([
      { ...panel[0], id: 1 },
      panel[1],
      { ...panel[2], id: 3 },
      panel[3],
      { ...panel[4], id: 5 },
      panel[5],
    ]);
  });

  it('2 — refused then retried with the same text, one row: NEITHER message takes it (W1)', () => {
    // The first 'retry' was refused before it was stored; the second is row 9. The panel cannot
    // tell which of the two is row 9, so it pairs neither: both offer delete after the next load.
    const panel = [user('hi', 1), user('retry'), user('retry')];
    const rows = [row(1, 'user', 'hi'), row(9, 'user', 'retry')];

    const result = withPersistedUserIds(panel, rows);

    expect(result[1].id).toBeUndefined();
    expect(result[2].id).toBeUndefined();
    expect(result).toBe(panel);
  });

  it('2b — stored then refused with the same text, one row: NEITHER message takes it (W1)', () => {
    // The first 'yes' is row 10, but its own id read was dropped because the second send started
    // first; the second 'yes' was refused (409) before it was stored. Pairing from the newest would
    // give row 10 to the refused copy, and deleting that copy would delete the stored turn.
    const panel = [user('build a deck', 1), assistant('Building 4 slide(s).', 2), user('yes'), assistant('Done.'), user('yes')];
    const rows = [row(1, 'user', 'build a deck'), row(2, 'assistant', 'Building 4 slide(s).'), row(10, 'user', 'yes'), row(11, 'assistant', 'Done.')];

    const result = withPersistedUserIds(panel, rows);

    expect(result.map(m => m.id)).toEqual([1, 2, undefined, undefined, undefined]);
    expect(result).toBe(panel);
  });

  it('2c — only the ambiguous content is skipped: other id-less messages in the same read still pair', () => {
    // Two id-less 'yes' and one 'yes' row (ambiguous), beside a unique 'make it blue' that is stored.
    const panel = [user('yes'), user('yes'), assistant('Done.'), user('make it blue'), assistant('Blue.')];
    const rows = [row(10, 'user', 'yes'), row(11, 'assistant', 'Done.'), row(12, 'user', 'make it blue'), row(13, 'assistant', 'Blue.')];

    const result = withPersistedUserIds(panel, rows);

    expect(result).toEqual([panel[0], panel[1], panel[2], { ...panel[3], id: 12 }, panel[4]]);
  });

  it('3 — a failed send in the middle does not shift later ids', () => {
    const panel = [
      user('first'),
      assistant('reply to first'),
      user('never stored'),
      user('third'),
      assistant('reply to third'),
    ];
    const rows = [
      row(1, 'user', 'first'),
      row(2, 'assistant', 'reply to first'),
      row(3, 'user', 'third'),
      row(4, 'assistant', 'reply to third'),
    ];

    const result = withPersistedUserIds(panel, rows);

    expect(result).toEqual([{ ...panel[0], id: 1 }, panel[1], panel[2], { ...panel[3], id: 3 }, panel[4]]);
    expect(result[2].id).toBeUndefined();
  });

  describe('4 — a row id already carried by a panel message is never assigned twice', () => {
    it('the identified message comes first', () => {
      const panel = [user('x', 5), assistant('reply'), user('x')];
      const rows = [row(5, 'user', 'x'), row(6, 'assistant', 'reply')];

      expect(withPersistedUserIds(panel, rows)).toBe(panel);
    });

    it('the identified message comes last', () => {
      const panel = [user('x'), assistant('reply'), user('x', 5)];
      const rows = [row(5, 'user', 'x'), row(6, 'assistant', 'reply')];

      expect(withPersistedUserIds(panel, rows)).toBe(panel);
    });

    it('an assistant message carries the id of a user row (C11: only the `taken` check guards this)', () => {
      const panel: Message[] = [
        { role: 'assistant', id: 9, content: 'a', timestamp: T },
        { role: 'user', content: 'x', timestamp: T },
      ];
      const rows = [row(9, 'user', 'x')];

      const result = withPersistedUserIds(panel, rows);

      expect(result[1].id).toBeUndefined();
      expect(result).toBe(panel);
    });
  });

  it("5 — rows without a numeric id are ignored (setupMocks' canned rows)", () => {
    // The mocked e2e catch-all serves the first two rows, without ids (tests/helpers/setup-mocks.ts).
    // The third has a null id, which is not a numeric id either.
    const canned = [
      { role: 'user', content: 'Create slides about cloud computing', created_at: '2026-01-08T20:39:00' },
      { role: 'assistant', content: "I'll create slides about cloud computing benefits.", created_at: '2026-01-08T20:39:30' },
      { id: null, role: 'user', content: 'Create slides about cloud computing', created_at: '2026-01-08T20:40:00' },
    ] as unknown as SessionMessage[];
    const panel = [user('Create slides about cloud computing'), assistant("I'll create slides about cloud computing benefits.")];

    const result = withPersistedUserIds(panel, canned);

    expect(result).toBe(panel);
    expect('id' in result[0]).toBe(false);
  });

  it('6 — a row that is not identical is not paired: image-injected text, or not a user row', () => {
    // SSE stores the message with the attached-image context appended (chat_service._inject_image_context).
    const injected =
      'Put our logo on the title slide\n\n[Attached images]\n'
      + '- Image ID img-1: "logo.png" (no description). Use: <img src="{{image:img-1}}" alt="logo.png" />';
    const panel = [user('Put our logo on the title slide'), assistant('Done.'), user('ok')];
    const rows = [row(3, 'user', injected), row(4, 'assistant', 'Done.'), row(5, 'assistant', 'ok')];

    expect(withPersistedUserIds(panel, rows)).toBe(panel);
  });

  it.each<[string, string, string]>([
    ['trailing whitespace', 'make it shorter', 'make it shorter '],
    ['leading whitespace', 'make it shorter', ' make it shorter'],
    ['letter case', 'make it shorter', 'Make it shorter'],
  ])('6b — a row whose content differs only in %s is not paired', (_label, panelText, rowText) => {
    const panel = [user(panelText), assistant('Done.')];
    const rows = [row(1, 'user', rowText), row(2, 'assistant', 'Done.')];

    expect(withPersistedUserIds(panel, rows)).toBe(panel);
  });

  it('7 — assistant messages, content and order are untouched (only user ids are added)', () => {
    const panel: Message[] = [
      user('use the sales table'),
      {
        role: 'assistant',
        content: 'Querying sales.',
        timestamp: T,
        tool_call: { name: 'query_genie_space', arguments: { query: 'sales by region' } },
      },
      { role: 'tool', content: '{"rows": 12}', timestamp: T, tool_call_id: 'call-1' },
      assistant('Building 2 slide(s).'), // emit-only progress line: never persisted
      assistant('Here are the sales slides.'),
      user('make slide 2 shorter'),
      assistant('Editing slide 2.'),
    ];
    const rows = [
      row(1, 'user', 'use the sales table'),
      row(2, 'assistant', 'Querying sales.'),
      row(3, 'tool', '{"rows": 12}'),
      row(4, 'assistant', 'Here are the sales slides.'),
      row(5, 'user', 'make slide 2 shorter'),
      row(6, 'assistant', 'Editing slide 2.'),
    ];
    const before = snapshot(panel);

    const result = withPersistedUserIds(panel, rows);

    expect(result).toEqual([
      { ...before[0], id: 1 },
      before[1],
      before[2],
      before[3],
      before[4],
      { ...before[5], id: 5 },
      before[6],
    ]);
    // Non-user messages are the very same objects, and the input is not mutated.
    for (const i of [1, 2, 3, 4, 6]) expect(result[i]).toBe(panel[i]);
    expect(panel).toEqual(before);
  });

  it.each<[string, Message[], SessionMessage[]]>([
    ['no persisted rows', [user('hello'), assistant('hi')], []],
    ['every user message already has its id', [user('hello', 1), assistant('hi', 2)], [row(1, 'user', 'hello'), row(2, 'assistant', 'hi')]],
    ['no row has the same content', [user('hello'), assistant('hi')], [row(1, 'user', 'goodbye'), row(2, 'assistant', 'hi')]],
    ['an empty panel', [], [row(1, 'user', 'hello')]],
  ])('8 — when nothing is paired it returns `panel` itself (%s)', (_label, panel, rows) => {
    expect(withPersistedUserIds(panel, rows)).toBe(panel);
  });

  it('9 — a row older than an already-identified message is never paired with an id-less message after it', () => {
    // Row 3 'x' is older than row 5, which the panel already shows as the message before the id-less 'x'.
    const panel = [user('x', 5), assistant('reply'), user('x')];
    const rows = [row(3, 'user', 'x'), row(4, 'assistant', 'reply'), row(5, 'user', 'x'), row(6, 'assistant', 'reply')];

    const result = withPersistedUserIds(panel, rows);

    expect(result[2].id).toBeUndefined();
    expect(result).toBe(panel);
  });

  it('9b — a row newer than an already-identified message is never paired with an id-less message before it', () => {
    // Row 7 'x' (sent after row 5, e.g. from another tab) is newer than the identified message
    // that FOLLOWS the id-less 'x' in the panel, so it cannot be that message's row.
    const panel = [user('x'), assistant('Something went wrong.'), user('y', 5), assistant('reply')];
    const rows = [row(5, 'user', 'y'), row(6, 'assistant', 'reply'), row(7, 'user', 'x')];

    const result = withPersistedUserIds(panel, rows);

    expect(result[0].id).toBeUndefined();
    expect(result).toBe(panel);
  });

  it('10 — messages are paired in panel order: a row newer than the row paired after a message is never taken by it', () => {
    // The panel shows 'a' then 'b'. Row 1 is 'b' and row 2 is 'a' (the order is the other way
    // round, e.g. a sibling tab sent them). 'b' takes row 1, so 'a' (shown BEFORE it) may only take
    // a row older than row 1, and there is none: it must not jump behind 'b' onto row 2.
    const panel = [user('a'), assistant('reply to a'), user('b'), assistant('reply to b')];
    const rows = [row(1, 'user', 'b'), row(2, 'user', 'a')];

    const result = withPersistedUserIds(panel, rows);

    expect(result).toEqual([panel[0], panel[1], { ...panel[2], id: 1 }, panel[3]]);
    expect(result[0].id).toBeUndefined();
  });
});
