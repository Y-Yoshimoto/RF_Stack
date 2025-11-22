// React
import React from 'react';
// MUI Components
import Container from '@mui/material/Container';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';

// fetchDataLoader
import { useLoaderData, useNavigate } from "react-router-dom";

type loaderResponseType = {
  id: number;
  type: string;
  name: string;
  params: string;
};

const SuccessComponent = ({ response }: { response: loaderResponseType }) => {
  return (
    <>
      <ul data-testid='response-info'>
        <li>Id: {response.id}</li>
        <li>Type: {response.type}</li>
        <li>Name: {response.name}</li>
        <li>Params: {response.params}</li>
      </ul>
    </>
  );
};

export const FetchLoaderSampleComponent: React.FC = () => {
  // loaderから取得したデータを取得
  const fetchData = useLoaderData() as loaderResponseType;
  // console.debug('Loader Data:', fetchData);
  // 読み込み中の状態表示について
  // https://react-router-docs-ja.techtalk.jp/start/framework/pending-ui#保留中の-ui
  return (<In_FetchLoaderSampleComponent fetchData={fetchData} />)
};

type InFetchLoaderSampleComponentProps = {
  fetchData: loaderResponseType;
};

export const In_FetchLoaderSampleComponent: React.FC<InFetchLoaderSampleComponentProps> = ({ fetchData }) => {

  const navigation = useNavigate();
  const requestingActions = () => navigation(`/FetchComponents-loader/${new Date().getTime()}`)

  return (
    <Container>
      <Typography variant='h4' data-testid='fetch-component-title'>Fetch Loader Component</Typography>
      <Box mt={2}>
        <Button variant='contained' onClick={requestingActions} data-testid='request-button'>
          Request
        </Button>
        <br />
        <SuccessComponent response={fetchData} />
      </Box>
    </Container>
  );
};

export default FetchLoaderSampleComponent;
