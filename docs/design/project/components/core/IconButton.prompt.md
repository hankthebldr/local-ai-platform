Icon-only square button for toolbars, canvas controls, and close/dock affordances.

```jsx
<IconButton label="Zoom in"><i data-lucide="plus" /></IconButton>
<IconButton label="Fullscreen" active><i data-lucide="maximize" /></IconButton>
<IconButton label="Close" bare>✕</IconButton>
```

Sizes `sm`/`md`/`lg`. `active` paints the teal selected state; `bare` is transparent until hover (use in dense toolbars).
