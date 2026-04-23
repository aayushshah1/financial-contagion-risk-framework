import neo4j from 'neo4j-driver';
import dotenv from 'dotenv';

dotenv.config();

const URI = process.env.NEO4J_URI || process.env.VITE_NEO4J_URI;
const USER = process.env.NEO4J_USERNAME || process.env.VITE_NEO4J_USERNAME;
const PASSWORD = process.env.NEO4J_PASSWORD || process.env.VITE_NEO4J_PASSWORD;

const driver = neo4j.driver(URI, neo4j.auth.basic(USER, PASSWORD));

async function run() {
  const session = driver.session();
  try {
    const res = await session.run('MATCH (n) RETURN n LIMIT 5');
    console.log("Nodes:");
    res.records.forEach(r => console.log(JSON.stringify(r.get('n').properties, null, 2), r.get('n').labels));
    
    const rels = await session.run('MATCH ()-[r]->() RETURN r LIMIT 5');
    console.log("Relationships:");
    rels.records.forEach(r => console.log(r.get('r').type, JSON.stringify(r.get('r').properties, null, 2)));
  } catch (err) {
    console.error(err);
  } finally {
    await session.close();
    await driver.close();
  }
}
run();
