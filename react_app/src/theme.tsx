import { createTheme } from '@mui/material/styles';
import { cyan, amber } from '@mui/material/colors';

// A custom theme for this app
const theme = createTheme({
  cssVariables: {
    nativeColor: true,
  },
  colorSchemes: {
    light: true,
    dark: true,
  },
  palette: {
    primary: cyan,
    secondary: amber,
  },
});

export default theme;