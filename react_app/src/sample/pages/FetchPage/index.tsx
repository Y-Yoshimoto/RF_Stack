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

// 成功時のコンポーネント
// eslint-disable-next-line
const SuccessComponent = ({ response }: { response: any }) => {
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

// API用 成功時のコンポーネントサンプル
const SuccessComponent_API = ({ response }: { response: any }) => {
  // サンプルレスポンス: {"id":123,"name":"sample","date":"2024-02-27"}
  return (
    <>
      <ul data-testid='response-info'>
        <li>Id: {response.id}</li>
        <li>Name: {response.name}</li>
        <li>Date: {response.date}</li>
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
        <FetchComponent key={key} resourceObj={{ url: `/static.json?key=${key}` }} renderSuccess={SuccessComponent} />
      </Box>
    </Container>
  );
};

export default FetchSampleComponent;
