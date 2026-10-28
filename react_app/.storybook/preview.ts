import { createElement } from 'react';
import type { Preview } from '@storybook/react-vite';
import { ThemeProvider } from '@mui/material/styles';
import theme from '../src/theme';

const preview: Preview = {
  // アプリと同じ MUI のテーマで描画する (CP の画面は、自身のコンポーネントが cp_theme に切り替える)
  decorators: [(Story) => createElement(ThemeProvider, { theme }, createElement(Story))],
  parameters: {
    controls: { matchers: { color: /(background|color)$/i, date: /Date$/i } },

    a11y: {
      // 'todo' - show a11y violations in the test UI only
      // 'error' - fail CI on a11y violations
      // 'off' - skip a11y checks entirely
      test: 'todo',
    },
  },
};

export default preview;
