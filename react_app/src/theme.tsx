import { createTheme } from '@mui/material/styles';
import { cyan, amber } from '@mui/material/colors';

// A custom theme for this app
const theme = createTheme({
  cssVariables: true,
  palette: {
    primary: cyan,
    secondary: amber,
  },
});

export default theme;