// React
import React from 'react';
import { useState } from 'react';
// MUI Components
import Container from '@mui/material/Container';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';

// export const TestSampleComponent: React.FC = () => {
export function TestSampleComponent() {
  // 表示テキストステート
  const [text, setText] = useState<string | null>(null);
  // デバック出力
  console.debug('App text: ' + text);

  return (
    <Container maxWidth='sm'>
      <Box sx={{ my: 4 }}>
        <Typography variant='h4' component='h1' sx={{ mb: 1 }}>
          This is a Create React App with TypeScript and Material-UI.
        </Typography>
      </Box>
      <Stack direction='row' spacing={2}>
        <Button variant='contained' onClick={() => setText('primary')} data-testid='button-primary'>
          primary
        </Button>
        <Button color='secondary' variant='contained' onClick={() => setText('secondary')} data-testid='button-secondary'>
          secondary
        </Button>
        <Button color='error' variant='contained' onClick={() => setText(null)} data-testid='button-clear'>
          clear
        </Button>
      </Stack>
      {text && (
        <Typography variant='h5' component='h2' sx={{ mt: 2 }} data-testid='text-label'>
          {text}
        </Typography>
      )}
    </Container>
  );
};

export default TestSampleComponent;
