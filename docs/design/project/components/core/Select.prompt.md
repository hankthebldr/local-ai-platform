Labelled dropdown that matches Input styling, with a custom teal-on-focus caret.

```jsx
<Select label="Default Role" options={['reasoning','coding','fast','general','uncensored']} />
<Select label="Category" mono options={[{value:'sec',label:'security'},{value:'ops',label:'devops'}]} />
```

Pass `options` (strings or `{value,label}`) or `<option>` children. `mono` for code-like values.
