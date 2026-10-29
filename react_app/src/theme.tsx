import { createTheme } from '@mui/material/styles';
import { cyan, amber, indigo, blueGrey, deepOrange } from '@mui/material/colors';

// 日本語の文言やテナントコード (英小文字) を大文字に変換しないよう、ボタンの text-transform を無効にする
const BUTTON_COMPONENTS = { MuiButton: { styleOverrides: { root: { textTransform: 'none' as const } } } };

// A custom theme for this app
const theme = createTheme({
  cssVariables: true,
  palette: {
    // 白地の上の文字・リンクで 4.5:1 以上のコントラストを確保するため、primary は cyan の濃い色を main にする
    primary: { ...cyan, main: cyan[800] },
    secondary: amber,
  },
  components: BUTTON_COMPONENTS,
});

/**
 * コントロールプレーン (CP) のテーマ
 * CP は SaaS 運用者向けの管理画面のため、AP (テナント利用者向け。cyan) と一目で区別できる配色にする。
 * CSS 変数の接頭辞を AP と分け、入れ子の ThemeProvider でも AP 側の変数を上書きしない。
 */
export const cp_theme = createTheme({
  cssVariables: { cssVarPrefix: 'cp' },
  palette: {
    primary: { main: indigo[900] },
    secondary: { main: deepOrange[900] },
    background: { default: blueGrey[50] },
  },
  components: BUTTON_COMPONENTS,
});

export default theme;
