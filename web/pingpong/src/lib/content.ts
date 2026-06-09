import {
	join,
	type Content,
	type MCPListToolsCallItem,
	type MCPServerCallItem,
	type Text,
	type WebSearchSource
} from '$lib/api';

type Replacement = {
	start: number;
	end: number;
	newValue: string;
};

export type InlineWebSource = {
	index: number;
	source: WebSearchSource;
};

export type ParsedTextContent = {
	content: string;
	inlineWebSources: InlineWebSource[];
};

export type MCPContent = MCPServerCallItem | MCPListToolsCallItem;
export type ContentBlock =
	| { type: 'content'; key: string; content: Content }
	| { type: 'mcp_group'; key: string; serverLabel: string; items: MCPContent[] }
	| { type: 'ci_group'; key: string; items: Content[]; isLast: boolean };

export const isMCPContent = (content: Content): content is MCPContent => {
	return content.type === 'mcp_server_call' || content.type === 'mcp_list_tools_call';
};

// Code-interpreter steps that should be collected under a single "Ran analysis" block.
export const isCodeInterpreterContent = (content: Content) => {
	return (
		content.type === 'code' ||
		content.type === 'code_output_logs' ||
		content.type === 'code_output_image_file' ||
		content.type === 'code_output_image_url' ||
		content.type === 'code_interpreter_call_placeholder'
	);
};

const getMCPServerKey = (content: MCPContent) => {
	return content.server_label || content.server_name || 'mcp';
};

export const groupMessageContent = (contents: Content[]): ContentBlock[] => {
	const blocks: ContentBlock[] = [];
	let index = 0;
	// Ordinal of each code-interpreter analysis within this message. Keyed by ordinal
	// rather than array position so the block keeps a stable identity when its
	// placeholder is swapped for the fetched result items.
	let ciGroupOrdinal = 0;

	while (index < contents.length) {
		const content = contents[index];

		if (isCodeInterpreterContent(content)) {
			const items: Content[] = [content];
			let cursor = index + 1;
			while (cursor < contents.length && isCodeInterpreterContent(contents[cursor])) {
				items.push(contents[cursor]);
				cursor += 1;
			}
			blocks.push({ type: 'ci_group', key: `ci-group-${ciGroupOrdinal}`, items, isLast: false });
			ciGroupOrdinal += 1;
			index = cursor;
			continue;
		}

		if (!isMCPContent(content)) {
			blocks.push({ type: 'content', key: `content-${index}`, content });
			index += 1;
			continue;
		}

		const serverKey = getMCPServerKey(content);
		const items: MCPContent[] = [content];
		let cursor = index + 1;
		while (cursor < contents.length) {
			const next = contents[cursor];
			if (!isMCPContent(next) || getMCPServerKey(next) !== serverKey) {
				break;
			}
			items.push(next);
			cursor += 1;
		}

		if (items.length > 1) {
			const label = items[0].server_name || items[0].server_label || 'MCP server';
			blocks.push({
				type: 'mcp_group',
				key: `mcp-group-${serverKey}-${index}`,
				serverLabel: label,
				items
			});
		} else {
			blocks.push({ type: 'content', key: `content-${index}`, content });
		}

		index = cursor;
	}

	const lastBlock = blocks[blocks.length - 1];
	if (lastBlock?.type === 'ci_group') {
		lastBlock.isLast = true;
	}
	return blocks;
};

/**
 * Rewrite OpenAI text content to incorporate annotations.
 */
export const parseTextContent = (
	text: Text,
	threadVersion: number = 2,
	baseUrl: string = '',
	messageId: string = ''
): ParsedTextContent => {
	let content = text.value;
	const replacements: Replacement[] = [];
	const inlineWebSources: InlineWebSource[] = [];
	let urlCitationIndex = 0;
	if (text.annotations) {
		for (const annotation of text.annotations) {
			if (
				annotation.type === 'file_path' &&
				((!annotation.file_path.file_id.startsWith('cfile_') && threadVersion === 3) ||
					threadVersion === 2)
			) {
				const { start_index, end_index, file_path } = annotation;
				const url = join(baseUrl, `/message/${messageId}/file/${file_path.file_id}`);
				replacements.push({ start: start_index, end: end_index, newValue: url });
			} else if (annotation.type === 'file_citation' && annotation.text !== 'responses_v3') {
				const { start_index, end_index, file_citation } = annotation;
				const fileName = ` (${file_citation.file_name})`;
				replacements.push({ start: start_index, end: end_index, newValue: fileName });
			} else if (annotation.type === 'url_citation') {
				// Drop a placeholder that the Markdown component swaps for an inline WebSourceChip.
				inlineWebSources.push({
					index: urlCitationIndex,
					source: {
						url: annotation.url,
						title: annotation.title || undefined,
						type: 'url'
					}
				});
				const needsLeadingSpace =
					annotation.start_index > 0 && !/\s/.test(text.value[annotation.start_index - 1]);
				replacements.push({
					start: annotation.start_index,
					end: annotation.end_index,
					newValue: `${needsLeadingSpace ? ' ' : ''}<span data-web-source-index="${urlCitationIndex}"></span>`
				});
				urlCitationIndex += 1;
			}
		}
	}

	// Apply replacements in reverse order (so that the indexes are still valid
	// while we are modifying the content).
	replacements.sort((a, b) => b.start - a.start);
	for (let i = 0; i < replacements.length; i++) {
		const { start, end, newValue } = replacements[i];
		content = content.slice(0, start) + newValue + content.slice(end);
	}

	return { content, inlineWebSources };
};

/**
 * Normalize newlines to use only '\n'.
 */
export const normalizeNewlines = (text: string) => text.replace(/\r\n/g, '\n');
