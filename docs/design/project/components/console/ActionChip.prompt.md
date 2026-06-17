Small mono chip with two jobs in the chat-led console: hover actions on assistant replies ("pin as step", "save as skill", "branch") and next-best-action nudges above the composer ("you've pinned 2 steps — convert to a workflow?"). Nudges are dismissible, never modal.

```jsx
<ActionChip icon={<i data-lucide="pin" />} accent>pin as step</ActionChip>
<ActionChip icon={<i data-lucide="scissors" />}>save as skill</ActionChip>
<ActionChip lg accent onDismiss={() => {}}>you've pinned 2 steps — convert to a workflow?</ActionChip>
```
