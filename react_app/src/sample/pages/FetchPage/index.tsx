// React
import React from 'react';
import { useState } from 'react';
// MUI Components
import Container from '@mui/material/Container';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';

// Fetchコンポーネント
import FetchComponent from '@/utils/libs/FetchComponents/component';

// 成功時のレスポンス(static.json)の型
type SampleResponse = { id: number; type: string; name: string };

// 成功時のコンポーネント
const SuccessComponent = ({ response }: { response: SampleResponse }) => {
  console.log('SuccessComponent', response);
  return (
    <>
      <ul data-testid='response-info'>
        <li>Id: {response.id}</li>
        <li>Type: {response.type}</li>
        <li>Name: {response.name}</li>
      </ul>
    </>
  );
};

export const FetchSampleComponent: React.FC = () => {
  const [key, setKey] = useState(0);

  // リクエスト再送ボタン
  const handleClick = () => { setKey(new Date().getTime()); };

  return (
    <Container>
      <Typography variant='h4' data-testid='fetch-component-title'>Fetch Component</Typography>
      <Box mt={2}>
        <Button variant='contained' onClick={handleClick} data-testid='request-button'>
          Request
        </Button>
        <br />
        <FetchComponent key={key} resource_obj={{ url: `/static.json?key=${key}` }} renderSuccess={SuccessComponent} />
      </Box>
    </Container>
  );
};

export default FetchSampleComponent;
